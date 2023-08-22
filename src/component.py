import logging
from datetime import datetime
from typing import List, Union, Any

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement

from client.client import OneDriveClient, OneDriveClientException
from configuration import Configuration, SyncActionConfiguration, Account

# Configuration variables
KEY_GROUP_ACCOUNT = 'account'
KEY_GROUP_SETTINGS = 'settings'
KEY_GROUP_DESTINATION = 'destination'
KEY_TENANT_ID = 'tenant_id'
KEY_SITE_URL = 'site_url'
KEY_FILE_PATH = 'file_path'
KEY_CUSTOM_TAG = 'custom_tag'
NEW_FILES_ONLY = 'new_files_only'
KEY_LIBRARY_NAME = 'library_name'
KEY_PERMANENT = 'permanent'

# List of required parameters
REQUIRED_PARAMETERS = []


class Component(ComponentBase):

    def __init__(self):
        super().__init__()
        self._configuration: Configuration

        self.refresh_token = self.configuration.oauth_credentials.data["refresh_token"]
        self.client_id = self.configuration.oauth_credentials.appKey
        self.client_secret = self.configuration.oauth_credentials.appSecret

    def run(self):

        self.list_sharepoint_libraries()
        exit()

        self._init_configuration()
        statefile = self.get_state_file()

        file_path = self._configuration.settings.file_path
        if not file_path:
            file_path = "*"
            logging.warning("File path is not set, the component will try to download everything "
                            "from authorized drive!")

        library_name = self._configuration.account.library_name

        last_modified_at = self._set_last_modified(statefile)

        client = self._get_client(self._configuration.account)
        try:
            client.download_files(file_path=file_path, output_dir=self.files_out_path,
                                  last_modified_at=last_modified_at, library_name=library_name)
        except OneDriveClientException as e:
            raise UserException(e) from e

        self._create_manifests(client)
        self._save_timestamp(client, file_path)

    def _save_timestamp(self, client, file_path) -> None:
        if client.freshest_file_timestamp:
            freshest_timestamp = client.freshest_file_timestamp.isoformat()
            self.write_state_file({"last_modified": freshest_timestamp})
            logging.info(f"Saving freshest file timestamp to statefile: {freshest_timestamp}")
        else:
            logging.warning(f"The component has not found any files matching filename: {file_path}")

    def _create_manifests(self, client) -> None:

        tag = self._configuration.destination.custom_tag
        tags = [tag] if tag else []

        permanent = self._configuration.destination.permanent_files
        if permanent:
            logging.info("Downloaded files will be stored as permanent files.")

        for filename in client.downloaded_files:
            file_def = self.create_out_file_definition(filename, tags=tags, is_permanent=permanent)
            self.write_manifest(file_def)

    def _set_last_modified(self, statefile) -> Union[str, Any]:
        get_new_only = self._configuration.settings.new_files_only
        last_modified_at = False
        if get_new_only:
            if statefile.get("last_modified", False):
                last_modified_at = datetime.fromisoformat(statefile.get("last_modified"))
                logging.info(f"Component will download files with lastModifiedDateTime > {last_modified_at}")
            else:
                logging.warning("last_modified timestamp not found in statefile, Cannot download new files only. "
                                "To resolve this, disable this option in row config or "
                                "set last_modified in statefile manually.")
        return last_modified_at

    def _init_configuration(self, init_sync_action: bool = False) -> None:
        """Sync Action does not require settings and destination objects."""
        if not init_sync_action:
            self.validate_configuration_parameters(Configuration.get_dataclass_required_parameters())
            self._configuration: Configuration = Configuration.load_from_dict(self.configuration.parameters)
        else:
            self.validate_configuration_parameters(SyncActionConfiguration.get_dataclass_required_parameters())
            self._configuration: Configuration = SyncActionConfiguration.load_from_dict(self.configuration.parameters)

    def _get_client(self, account_params: Account) -> OneDriveClient:
        tenant_id = account_params.tenant_id
        site_url = account_params.site_url
        try:
            client = OneDriveClient(refresh_token=self.refresh_token, files_out_folder=self.files_out_path,
                                    client_id=self.client_id, client_secret=self.client_secret,
                                    tenant_id=tenant_id, site_url=site_url)
        except OneDriveClientException as e:
            raise UserException(e) from e

        return client

    @sync_action("listLibraries")
    def list_sharepoint_libraries(self) -> List[SelectElement]:
        self._init_configuration(init_sync_action=True)
        client = self._get_client(self._configuration.account)
        libraries = client.get_document_libraries(self._configuration.account.site_url)

        return [
            SelectElement(
                label=library['name'],
                value="Shared Documents" if library['name'] == "Documents" else library['webUrl'].split("/")[-1]
            )
            for library in libraries
        ]


# Main entrypoint
if __name__ == "__main__":
    try:
        comp = Component()
        comp.execute_action()
    except UserException as exc:
        logging.exception(exc)
        exit(1)
    except Exception as exc:
        logging.exception(exc)
        exit(2)
