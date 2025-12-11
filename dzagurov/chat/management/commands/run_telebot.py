from django.core.management.base import BaseCommand
from chat.telegram_bot import run_bot

class Command(BaseCommand):
    help = "Run Telegram bot (polling)"
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting Telegram bot (polling)..."))
        run_bot()
