import logging

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
import keboola.utils.date as dutils
from datetime import datetime

from client.OneDriveClient import OneDriveClient, OneDriveClientException

# Configuration variables
KEY_TENANT_ID = 'tenant_id'
KEY_SITE_NAME = 'site_name'
KEY_FOLDER = 'folder'
KEY_MASK = 'mask'
KEY_CUSTOM_TAG = 'custom_tag'
KEY_LAST_MODIFIED_AT = 'last_modified_at'

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
        statefile = self.get_state_file()
        folder = params.get(KEY_FOLDER, "/") or "/"
        if not folder.startswith("/"):
            folder = "/"+folder
        mask = params.get(KEY_MASK, "*") or "*"
        tag = params.get(KEY_CUSTOM_TAG, False)
        tags = [tag] if tag else []
        last_modified_at = params.get(KEY_LAST_MODIFIED_AT, None)
        if last_modified_at:
            if last_modified_at == "last run":
                if statefile.get("last_run", False):
                    last_modified_at = datetime.strptime(statefile.get("last_run"), '%Y-%m-%d %H:%M:%S')
                else:
                    logging.error("last_run not found in statefile. Cannot filter based on time.")
                    last_modified_at = None
            else:
                last_modified_at, _ = dutils.parse_datetime_interval(last_modified_at, 'today')
            logging.info(f"Component will download files with lastModifiedDateTime > {last_modified_at}")

        client = self.get_client(params)
        logging.info(f"Component will download files from folder: {folder} with mask: {mask}")
        try:
            client.download_files(folder_path=folder, file_mask=mask, output_dir=self.files_out_path,
                                  last_modified_at=last_modified_at)
        except OneDriveClientException as e:
            raise UserException(e) from e

        for filename in client.downloaded_files:
            file_def = self.create_out_file_definition(filename, tags=tags)
            self.write_manifest(file_def)

        self.write_state_file({"last_run": datetime.today().strftime('%Y-%m-%d %H:%M:%S')})

    def get_client(self, params):
        tenant_id = params.get(KEY_TENANT_ID, None)
        site_name = params.get(KEY_SITE_NAME, None)
        try:
            client = OneDriveClient(refresh_token=self.refresh_token, files_out_folder=self.files_out_path,
                                    client_id=self.client_id, client_secret=self.client_secret,
                                    tenant_id=tenant_id, site_name=site_name)
        except OneDriveClientException as e:
            raise UserException(e) from e

        return client

    @sync_action("listSites")
    def list_sharepoint_sites(self):
        params = self.configuration.parameters
        client = self.get_client(params)
        sites = client.list_sharepoint_sites()

        transformed_list = []
        for site in sites:
            transformed_site = {
                'label': site['name'],
                'value': site['name']
            }
            transformed_list.append(transformed_site)

        return transformed_list


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
