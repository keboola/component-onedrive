import logging
from keboola.component.base import ComponentBase
from keboola.component.exceptions import UserException
from client.OneDriveBusiness import OneDriveBusinessClient
from client.OneDriveClient import OneDriveClient

# Configuration variables
KEY_TENANT_ID = 'tenant_id'
KEY_SITE_NAME = 'site_name'
KEY_FOLDER = 'folder'
KEY_MASK = 'mask'
KEY_ACCOUNT_TYPE = 'account_type'
KEY_CUSTOM_TAG = 'custom_tag'

# List of required parameters
REQUIRED_PARAMETERS = [KEY_ACCOUNT_TYPE]
REQUIRED_IMAGE_PARS = []


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
        self.validate_configuration_parameters(REQUIRED_PARAMETERS)
        self.validate_image_parameters(REQUIRED_IMAGE_PARS)
        params = self.configuration.parameters
        folder = params.get(KEY_FOLDER, "/") or "/"
        if not folder.startswith("/"):
            folder = "/"+folder
        mask = params.get(KEY_MASK, "*") or "*"
        tag = params.get(KEY_CUSTOM_TAG, False)
        tags = [tag] if tag else []

        account_type = self.configuration.parameters.get("account_type")
        client = self.get_client(account_type)
        logging.info(f"Component will download files from folder: {folder} with mask: {mask}")
        client.download_files(folder_path=folder, file_mask=mask, output_dir=self.files_out_path)

        for filename in client.downloaded_files:
            file_def = self.create_out_file_definition(filename, tags=tags)
            self.write_manifest(file_def)

    def get_client(self, account_type):
        if account_type == "private":
            client = OneDriveClient(refresh_token=self.refresh_token, files_out_folder=self.files_out_path,
                                    client_id=self.client_id, client_secret=self.client_secret)
        elif account_type == "work_school":
            tenant_id = self.configuration.parameters.get(KEY_TENANT_ID)
            site_name = self.configuration.parameters.get(KEY_SITE_NAME)
            logging.info(f"Site name set to {site_name}")

            client = OneDriveBusinessClient(refresh_token=self.refresh_token,
                                            files_out_folder=self.files_out_path,
                                            client_id=self.client_id,
                                            client_secret=self.client_secret,
                                            tenant_id=tenant_id,
                                            site_name=site_name)
        else:
            raise UserException(f"Unsupported Account Type: {account_type}")
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
