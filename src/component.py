import logging
from datetime import datetime
from typing import List

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement

from client.OneDriveClient import OneDriveClient, OneDriveClientException


# Configuration variables
KEY_GROUP_ACCOUNT = 'account'
KEY_GROUP_SETTINGS = 'settings'
KEY_GROUP_DESTINATION = 'destination'
KEY_TENANT_ID = 'tenant_id'
KEY_SITE_URL = 'site_url'
KEY_FILE_PATH = 'file_path'
KEY_CUSTOM_TAG = 'custom_tag'
NEW_FILES_ONLY = 'new_files_only'

# List of required parameters
REQUIRED_PARAMETERS = []


class Component(ComponentBase):

    def __init__(self):
        super().__init__()
        self.refresh_token = self.configuration.oauth_credentials.data["refresh_token"]
        self.client_id = self.configuration.oauth_credentials["appKey"]
        self.client_secret = self.configuration.oauth_credentials["appSecret"]
        self.authorized_for = (
            self.configuration.config_data["authorization"]["oauth_api"]["credentials"]["authorizedFor"]
        )

    def run(self):
        params = self.configuration.parameters
        account_params = params.get(KEY_GROUP_ACCOUNT)
        settings_params = params.get(KEY_GROUP_SETTINGS)
        destination_params = params.get(KEY_GROUP_DESTINATION)
        statefile = self.get_state_file()

        file_path = settings_params.get(KEY_FILE_PATH, None)
        if not file_path:
            file_path = "*"
            logging.warning("File path is not set, the component will try to download everything "
                            "from authorized drive!")
        """
        if not folder.startswith("/"):
            folder = "/"+folder
        """
        tag = destination_params.get(KEY_CUSTOM_TAG, False)
        tags = [tag] if tag else []

        get_new_only = settings_params.get(NEW_FILES_ONLY, False)
        last_modified_at = False
        if get_new_only:
            if statefile.get("last_modified", False):
                last_modified_at = datetime.fromisoformat(statefile.get("last_modified"))
                logging.info(f"Component will download files with lastModifiedDateTime > {last_modified_at}")
            else:
                logging.warning("last_modified timestamp not found in statefile, Cannot download new files only. "
                                "To resolve this, disable this option in row config or "
                                "set last_modified in statefile manually.")

        client = self.get_client(account_params)
        try:
            client.download_files(file_path=file_path, output_dir=self.files_out_path,
                                  last_modified_at=last_modified_at)
        except OneDriveClientException as e:
            raise UserException(e) from e

        for filename in client.downloaded_files:
            file_def = self.create_out_file_definition(filename, tags=tags)
            self.write_manifest(file_def)

        freshest_timestamp = client.freshest_file_timestamp.isoformat()
        self.write_state_file({"last_modified": freshest_timestamp})
        logging.info(f"Saving freshest file timestamp to statefile: {freshest_timestamp}")

    def get_client(self, account_params):
        tenant_id = account_params.get(KEY_TENANT_ID, None)
        site_url = account_params.get(KEY_SITE_URL, None)
        try:
            client = OneDriveClient(refresh_token=self.refresh_token, files_out_folder=self.files_out_path,
                                    client_id=self.client_id, client_secret=self.client_secret,
                                    tenant_id=tenant_id, site_url=site_url)
        except OneDriveClientException as e:
            raise UserException(e) from e

        return client


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
