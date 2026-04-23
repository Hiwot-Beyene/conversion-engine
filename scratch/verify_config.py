try:
    from agent.config import settings
    print("✅ Settings loaded successfully")
    print(f"Environment: {settings.ENVIRONMENT}")
    print(f"DB URL: {settings.db.url}")
except SystemExit:
    print("\nValidated: The system correctly exited due to missing required variables.")
except Exception as e:
    print(f"Unexpected error: {e}")
