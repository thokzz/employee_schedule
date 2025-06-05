try:
    from .email_service import EmailService
    __all__ = ['EmailService']
except ImportError:
    print("DEBUG: EmailService import failed")
    __all__ = []