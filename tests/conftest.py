"""
Shared pytest setup.

Disables the "new voucher" e-mail notification for the whole test run so
tests never open an SMTP connection or need a password.
"""
import os

os.environ["VOUCHER_DISABLE_EMAIL"] = "1"
