from .constants import APP_ID, APP_NAME

__all__ = ["APP_ID", "APP_NAME", "DashboardApp"]


def __getattr__(name):
    if name == "DashboardApp":
        from .window import DashboardApp

        return DashboardApp
    raise AttributeError(name)
