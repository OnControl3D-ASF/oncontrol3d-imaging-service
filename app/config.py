from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    orthanc_url: str = "http://localhost:8042"
    orthanc_username: str | None = None
    orthanc_password: str | None = None

    public_base_url: str = "http://localhost:8001"
    volview_url: str = "http://localhost:8042/volview/index.html"

    storage_dir: str = "storage"

    class Config:
        env_file = ".env"


settings = Settings()
