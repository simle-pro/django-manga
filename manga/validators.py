from django.contrib.auth.password_validation import (
    CommonPasswordValidator as BaseCommonPasswordValidator,
    MinimumLengthValidator as BaseMinimumLengthValidator,
)

# Только очевидно простые пароли — остальное разрешено
COMMON_PASSWORDS = {
    '123456', '654321', '123456789', '12345678', '1234567',
    '111111', '000000', '123123', '123321', '6543210',
    'qwerty', 'qwerty123', 'password', 'iloveyou',
}


class MinimumLengthValidator(BaseMinimumLengthValidator):
    def get_error_message(self):
        return f'Пароль должен содержать минимум {self.min_length} символов.'

    def get_help_text(self):
        return f'Минимальная длина пароля — {self.min_length} символов.'


class CommonPasswordValidator(BaseCommonPasswordValidator):
    def __init__(self, password_list_path=None):
        self.passwords = COMMON_PASSWORDS

    def get_error_message(self):
        return 'Этот пароль слишком простой. Придумайте другой.'

    def get_help_text(self):
        return 'Пароль не должен быть слишком простым.'
