"""
sensors/views.py — SensorViewSet and SensorReadingViewSet
==========================================================
SensorReadingViewSet — immutability:
  http_method_names excludes PUT, PATCH, DELETE.  DRF returns 405 Method Not
  Allowed automatically; no custom logic needed.

SensorReadingViewSet — pagination:
  Uses the global PageNumberPagination (PAGE_SIZE=50) from settings.  The
  viewset does not override pagination_class so the project default applies.

SensorReadingViewSet.latest():
  MySQL-compatible correlated subquery — see implementation_plan.md Fix 2.
  The subquery resolves the pk of the most-recent SensorReading for each Sensor.
  This hits the compound index idx_reading_sensor_ts (sensor, timestamp) from
  Phase 1 for the inner ORDER BY / LIMIT.

SensorReadingViewSet.history():
  Accepts ?sensor=<id>&range=24h|7d|30d.
  24h  → TruncHour  buckets (24 points)
  7d   → TruncDay   buckets (7 points)
  30d  → TruncDay   buckets (30 points)
  Returns a list of dicts: [{bucket, avg_pm25, avg_pm10, avg_temp, avg_humidity}]
  No serializer class needed — the ORM aggregate result is already a plain dict.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Avg, Count, OuterRef, Q, Subquery
from django.db.models.functions import TruncDay, TruncHour
from django.utils import timezone

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .aqi import compute_aqi, resolve_location
from .external_aqi import fetch_external_aqi
from .geocoding import geocode
from .models import Sensor, SensorReading
from .permissions import IsAdminOrReadOnly, IsAuthenticatedReadOrCreate
from .serializers import SensorReadingSerializer, SensorSerializer


class SensorViewSet(viewsets.ModelViewSet):
    """
    CRUD for Sensor objects.
    Write operations (POST/PUT/PATCH/DELETE) require admin role.
    Read operations are open to any authenticated user.
    """

    serializer_class = SensorSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        return (
            Sensor.objects
            .annotate(reading_count=Count("readings"))
            .order_by("sensor_code")
        )


class SensorReadingViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Ingest and retrieve SensorReading rows.

    Uses explicit mixins (not ModelViewSet) so that PUT / PATCH / DELETE
    routes are never registered by the router at all.  DRF returns 405
    before any permission check runs, which is the correct behaviour for
    immutable resources.

    Permissions:
      POST / GET: any authenticated user (simulator uses Token auth).
      PUT / PATCH / DELETE: not routed — 405 from the router.

    Query filters (GET list):
      ?sensor=<id>   — filter by sensor primary key
      ?since=<ISO>   — only readings at or after this datetime (UTC)

    Custom actions:
      GET /readings/latest/           — one row per sensor, most-recent timestamp
      GET /readings/history/          — time-bucketed averages
        ?sensor=<id>  (required)
        &range=24h|7d|30d  (default: 24h)
    """

    serializer_class = SensorReadingSerializer
    # IsAuthenticated (not IsAuthenticatedReadOrCreate) is correct here.
    # Immutability is enforced at the routing layer: no UpdateModelMixin means
    # the router never registers PUT/PATCH/DELETE routes, so the router itself
    # returns 405 before any permission check for those methods.
    # If we used IsAuthenticatedReadOrCreate, DRF's permission check would
    # run first and return 403 for PUT — masking the real reason (no route).
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = SensorReading.objects.select_related("sensor").order_by("-timestamp")
        sensor_id = self.request.query_params.get("sensor")
        since = self.request.query_params.get("since")
        if sensor_id:
            qs = qs.filter(sensor_id=sensor_id)
        if since:
            qs = qs.filter(timestamp__gte=since)
        return qs

    def perform_create(self, serializer):
        """
        Save the reading then run both the threshold alert engine (Phase 4)
        and the ML anomaly scorer (Phase 5) in sequence.

        Both imports are local to avoid circular imports:
          sensors → alerts.services  (ok at call time)
          sensors → analytics.ml     (ok at call time)
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)

        reading = serializer.save()

        # ── Phase 4: threshold alert engine ───────────────────────────────────
        from alerts.services import check_thresholds
        threshold_alerts = check_thresholds(reading)
        if threshold_alerts:
            _log.info(
                "Threshold check: %d alert(s) for reading id=%d",
                len(threshold_alerts), reading.pk,
            )

        # ── Phase 5: ML anomaly scorer ────────────────────────────────────────
        from analytics.ml import score_reading
        from alerts.services import _is_duplicate
        from django.conf import settings
        from datetime import timedelta

        try:
            is_anomaly, score = score_reading(reading)
        except Exception as exc:  # noqa: BLE001
            _log.warning("ML scoring failed for reading id=%d: %s", reading.pk, exc)
            is_anomaly, score = False, 0.0

        if is_anomaly:
            from alerts.models import Alert
            cooldown = timedelta(seconds=getattr(settings, "ALERT_COOLDOWN_SECONDS", 300))
            # Dedup: skip if an open ML alert for this sensor already exists
            # within the cooldown window.  Use parameter="anomaly" to
            # distinguish ML composite alerts from per-parameter threshold alerts.
            if not _is_duplicate(reading.sensor_id, "anomaly", cooldown):
                Alert.objects.create(
                    sensor=reading.sensor,
                    reading=reading,
                    alert_type=Alert.TYPE_ML,
                    parameter="anomaly",
                    value=round(score, 6),
                    severity=Alert.SEV_HIGH,
                    status=Alert.STATUS_OPEN,
                )
                _log.info(
                    "ML anomaly alert created for sensor %s (score=%.4f)",
                    reading.sensor.sensor_code, score,
                )

    # ── Custom actions ────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="latest")
    def latest(self, request):
        """
        Return the most-recent SensorReading for each sensor.

        MySQL-compatible implementation — DISTINCT ON is PostgreSQL-only.
        Uses a correlated subquery:

            SELECT * FROM sensors_sensorreading
            WHERE id IN (
                SELECT (
                    SELECT id FROM sensors_sensorreading sr2
                    WHERE sr2.sensor_id = s.id
                    ORDER BY sr2.timestamp DESC LIMIT 1
                )
                FROM sensors_sensor s
            )

        The inner subquery hits the compound index idx_reading_sensor_ts.
        """
        # Subquery: for each Sensor row, the PK of its latest reading.
        latest_pk_sq = (
            SensorReading.objects
            .filter(sensor=OuterRef("pk"))
            .order_by("-timestamp")
            .values("pk")[:1]
        )
        sensor_filter = request.query_params.get("sensor")
        sensor_qs = Sensor.objects.all()
        if sensor_filter:
            sensor_qs = sensor_qs.filter(pk=sensor_filter)

        pks = (
            sensor_qs
            .annotate(latest_pk=Subquery(latest_pk_sq))
            .exclude(latest_pk=None)
            .values_list("latest_pk", flat=True)
        )
        queryset = (
            SensorReading.objects
            .filter(pk__in=pks)
            .select_related("sensor")
            .order_by("sensor__sensor_code")
        )
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="history")
    def history(self, request):
        """
        Time-bucketed average readings for a sensor.

        Query params:
          ?sensor=<id>  (required)
          ?range=24h|7d|30d  (default: 24h)

        Response: list of dicts
          [{bucket (ISO), avg_pm25, avg_pm10, avg_temp, avg_humidity}]

        24h → TruncHour (up to 24 data points)
        7d  → TruncDay  (up to 7 data points)
        30d → TruncDay  (up to 30 data points)
        """
        sensor_id = request.query_params.get("sensor")
        if not sensor_id:
            return Response(
                {"detail": "?sensor=<id> is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        range_param = request.query_params.get("range", "24h")
        now = timezone.now()

        range_map = {
            "24h": (timedelta(hours=24), TruncHour),
            "7d":  (timedelta(days=7),   TruncDay),
            "30d": (timedelta(days=30),  TruncDay),
        }
        if range_param not in range_map:
            return Response(
                {"detail": "range must be one of: 24h, 7d, 30d."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        delta, trunc_fn = range_map[range_param]
        since = now - delta

        data = (
            SensorReading.objects
            .filter(sensor_id=sensor_id, timestamp__gte=since)
            .annotate(bucket=trunc_fn("timestamp"))
            .values("bucket")
            .annotate(
                avg_pm25=Avg("pm25"),
                avg_pm10=Avg("pm10"),
                avg_temp=Avg("temperature"),
                avg_humidity=Avg("humidity"),
            )
            .order_by("bucket")
        )

        result = [
            {
                "bucket": row["bucket"].isoformat(),
                "avg_pm25": row["avg_pm25"],
                "avg_pm10": row["avg_pm10"],
                "avg_temp": row["avg_temp"],
                "avg_humidity": row["avg_humidity"],
            }
            for row in data
        ]
        return Response(result)


import re


class LocationSearchView(APIView):
    """
    GET /api/v1/sensors/search/?location=<query>
    GET /api/v1/sensors/search/?lat=<latitude>&lon=<longitude>

    3-step search flow (by name):
    -----------------------------
    1. Internal: case-insensitive partial match on Sensor.location (also
       checks CITY_ALIASES so "Bangalore" hits sensors stored as "Bengaluru").
       Returns VAYU's own live sensor data tagged source="vayu_sensor".

    2. Geocode (Nominatim): if no internal match, resolve the query to
       (lat, lon).  Returns 404 if geocoding fails.

    3. External (WAQI): fetch nearest monitoring station data for the
       geocoded coordinates.  Results are cached 15 minutes per location.
       Returns 404 if WAQI has no nearby station.

    Direct coordinate search (by lat/lon):
    --------------------------------------
    Directly fetches nearest WAQI monitoring station data for given (lat, lon)
    with a rounded-coordinate 15-minute cache key.

    Session: stores the searched location in request.session["last_location"]
    on every successful match (internal or external).

    Authentication: same as all sensor endpoints — IsAuthenticated.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        lat_param = request.query_params.get("lat") or request.query_params.get("latitude")
        lon_param = request.query_params.get("lon") or request.query_params.get("longitude")

        # ── Branch A: Coordinate-based search (Geolocation) ───────────────────
        if lat_param is not None or lon_param is not None:
            if lat_param is None or lon_param is None:
                return Response(
                    {"detail": "Both ?lat= and ?lon= parameters are required for coordinate search."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                lat = float(lat_param)
                lon = float(lon_param)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Latitude and longitude must be valid floating-point numbers."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                return Response(
                    {"detail": "Coordinates out of valid range (lat: -90..90, lon: -180..180)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            rounded_lat = round(lat, 3)
            rounded_lon = round(lon, 3)
            cache_key = f"vayu_waqi_geo_{rounded_lat:.3f}_{rounded_lon:.3f}"

            external = fetch_external_aqi(lat, lon, cache_key)
            if external is None:
                token = getattr(settings, "WAQI_API_TOKEN", "")
                if not token:
                    detail = (
                        f"No WAQI_API_TOKEN is configured. Set it in .env to enable public AQI data."
                    )
                else:
                    detail = f"No air quality data available for coordinates ({lat:.4f}, {lon:.4f})."
                return Response({"detail": detail}, status=status.HTTP_404_NOT_FOUND)

            location_label = external.get("station_name") or f"{lat:.4f}, {lon:.4f}"
            request.session["last_location"] = location_label
            return Response({"query": location_label, "results": [external]})

        # ── Branch B: Text-based location search ──────────────────────────────
        raw_query = request.query_params.get("location", "")
        if not raw_query or not raw_query.strip():
            return Response(
                {"detail": "?location=<city name> is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Length cap (100 characters max)
        capped_query = raw_query[:100].strip()

        # Regex whitelist: letters, numbers, spaces, commas, hyphens, periods only
        sanitized_query = re.sub(r"[^\w\s,.-]", "", capped_query, flags=re.UNICODE).strip()
        sanitized_query = re.sub(r"\s+", " ", sanitized_query)

        if not sanitized_query:
            return Response(
                {"detail": "Location query contains no valid characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        query = sanitized_query

        # ── Step 1: internal sensor match ─────────────────────────────────────
        # Build OR filter covering the original query + any city alias
        search_terms = resolve_location(query)
        q_filter = Q()
        for term in search_terms:
            q_filter |= Q(location__icontains=term)

        matched_sensors = (
            Sensor.objects
            .filter(q_filter)
            .order_by("sensor_code")
        )

        if matched_sensors.exists():
            # Fetch latest reading for each matched sensor (reuse subquery pattern)
            latest_pk_sq = (
                SensorReading.objects
                .filter(sensor=OuterRef("pk"))
                .order_by("-timestamp")
                .values("pk")[:1]
            )
            pks = (
                matched_sensors
                .annotate(latest_pk=Subquery(latest_pk_sq))
                .exclude(latest_pk=None)
                .values_list("latest_pk", flat=True)
            )
            readings_qs = (
                SensorReading.objects
                .filter(pk__in=pks)
                .select_related("sensor")
                .order_by("sensor__sensor_code")
            )

            results = []
            for reading in readings_qs:
                aqi_data = compute_aqi(reading.pm25, reading.pm10)
                results.append({
                    "source": "vayu_sensor",
                    "sensor_id":   reading.sensor.id,
                    "sensor_code": reading.sensor.sensor_code,
                    "location":    reading.sensor.location,
                    "latitude":    reading.sensor.latitude,
                    "longitude":   reading.sensor.longitude,
                    "status":      reading.sensor.status,
                    "pm25":        reading.pm25,
                    "pm10":        reading.pm10,
                    "temperature": reading.temperature,
                    "humidity":    reading.humidity,
                    "timestamp":   reading.timestamp.isoformat(),
                    "aqi":         aqi_data["aqi"],
                    "aqi_category": aqi_data["category"],
                    "pm25_sub":    aqi_data["pm25_sub"],
                    "pm10_sub":    aqi_data["pm10_sub"],
                })

            request.session["last_location"] = query
            return Response({"query": query, "results": results})

        # ── Step 2: geocode via Nominatim ─────────────────────────────────────
        coords = geocode(query)
        if coords is None:
            return Response(
                {"detail": f"Location '{query}' could not be found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        lat, lon = coords
        safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", query.lower().strip())
        cache_key = f"vayu_waqi_{safe_key}"

        # ── Step 3: external AQI via WAQI (multi-step fallback) ───────────────
        external = fetch_external_aqi(lat, lon, cache_key, query=query)
        if external is None:
            token = getattr(settings, "WAQI_API_TOKEN", "")
            if not token:
                detail = (
                    f"No VAYU sensor found for '{query}' and no WAQI_API_TOKEN "
                    f"is configured. Set it in .env to enable public AQI data."
                )
            else:
                detail = f"No air quality monitoring station found near '{query}'. Try a nearby larger city."
            return Response({"detail": detail}, status=status.HTTP_404_NOT_FOUND)

        # External result — return wrapped in uniform results list
        request.session["last_location"] = query
        return Response({"query": query, "results": [external]})


class SensorMapView(APIView):
    """
    GET /api/v1/sensors/map/

    Returns all VAYU sensors that have coordinates (latitude + longitude set),
    along with their latest AQI reading. Sensors with null lat/lon are silently
    excluded — they simply have no point to place on the map.

    Response shape per sensor:
    {
        "id":           int,
        "sensor_code":  str,
        "location":     str,
        "latitude":     float,
        "longitude":    float,
        "status":       str,
        "aqi":          int | null,
        "aqi_category": str,
        "pm25":         float | null,
        "pm10":         float | null,
        "temperature":  float | null,
        "humidity":     float | null,
        "timestamp":    str (ISO 8601) | null
    }

    Requires authentication (IsAuthenticated). Read-only endpoint.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Only sensors that have geocoordinates set
        geocoded_sensors = (
            Sensor.objects
            .exclude(latitude__isnull=True)
            .exclude(longitude__isnull=True)
            .order_by("sensor_code")
        )

        # For each geocoded sensor, fetch the latest reading via correlated subquery
        latest_pk_sq = (
            SensorReading.objects
            .filter(sensor=OuterRef("pk"))
            .order_by("-timestamp")
            .values("pk")[:1]
        )
        sensors_with_latest = (
            geocoded_sensors
            .annotate(latest_pk=Subquery(latest_pk_sq))
        )

        # Build a mapping from sensor pk → latest SensorReading for efficient lookup
        latest_pks = [s.latest_pk for s in sensors_with_latest if s.latest_pk is not None]
        latest_readings = {
            r.sensor_id: r
            for r in SensorReading.objects.filter(pk__in=latest_pks).select_related("sensor")
        }

        results = []
        for sensor in sensors_with_latest:
            reading = latest_readings.get(sensor.pk)
            aqi_data = compute_aqi(
                reading.pm25 if reading else None,
                reading.pm10 if reading else None,
            )
            results.append({
                "id":           sensor.pk,
                "sensor_code":  sensor.sensor_code,
                "location":     sensor.location,
                "latitude":     sensor.latitude,
                "longitude":    sensor.longitude,
                "status":       sensor.status,
                "aqi":          aqi_data["aqi"],
                "aqi_category": aqi_data["category"],
                "pm25":         reading.pm25 if reading else None,
                "pm10":         reading.pm10 if reading else None,
                "temperature":  reading.temperature if reading else None,
                "humidity":     reading.humidity if reading else None,
                "timestamp":    reading.timestamp.isoformat() if reading else None,
            })

        return Response(results)

