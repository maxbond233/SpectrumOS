import uvicorn

from spectrum.api.research import create_research_app
from spectrum.runtime_config import runtime_settings


def main() -> None:
    settings = runtime_settings()
    uvicorn.run(create_research_app(), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
