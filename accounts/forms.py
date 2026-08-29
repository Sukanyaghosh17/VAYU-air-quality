from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model

User = get_user_model()


class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            "class": "form-input",
            "placeholder": "Enter your email address",
            "autocomplete": "email",
        }),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
        widgets = {
            "username": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "Choose a username",
                "autocomplete": "username",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Apply form-input class to password fields as well
        if "password1" in self.fields:
            self.fields["password1"].widget.attrs.update({
                "class": "form-input",
                "placeholder": "Create a password",
                "autocomplete": "new-password",
            })
        if "password2" in self.fields:
            self.fields["password2"].widget.attrs.update({
                "class": "form-input",
                "placeholder": "Confirm your password",
                "autocomplete": "new-password",
            })

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get("email", "")
        user.role = User.ROLE_USER
        if commit:
            user.save()
        return user
