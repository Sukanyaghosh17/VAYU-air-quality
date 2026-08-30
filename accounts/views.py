from django.contrib.auth import login
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView
from .forms import SignUpForm


class SignUpView(CreateView):
    """Sign-up panel of the combined animated auth experience."""
    form_class = SignUpForm
    template_name = "registration/auth.html"
    success_url = reverse_lazy("home")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["auth_mode"] = "signup"
        return ctx

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        return redirect(self.success_url)
