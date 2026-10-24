from backend.app.main import create_app
from scripts.runtime_package import deployment_settings

app = create_app(deployment_settings())
