"""VPS entry point. FastAPI lifespan owns telemetry, receivers, relays and OBS."""

from ratonet.dashboard.main import main


if __name__ == "__main__":
    main()
