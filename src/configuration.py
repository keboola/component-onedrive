from dataclasses import dataclass


@dataclass
class Account:
    tenant_id: str = ""
    site_url: str = ""
    library_name: str = ""


@dataclass
class Settings:
    file_path: str
    new_files_only: bool = False


@dataclass
class Destination:
    custom_tag: str = ""
    permanent: bool = False


@dataclass
class Configuration:
    account: Account
    settings: Settings
    destination: Destination
