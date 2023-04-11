import logging

from keboola.component.base import ComponentBase
from keboola.component.exceptions import UserException

from client.OneDriveBusiness import OneDriveBusinessClient
from client.OneDriveClient import OneDriveClient

# configuration variables
KEY_TENANT_ID = 'tenant_id'
KEY_SITE_NAME = 'site_name'
KEY_FOLDER = 'folder'
KEY_MASK = 'mask'

# list of mandatory parameters => if some is missing,
# component will fail with readable message on initialization.
REQUIRED_PARAMETERS = []
REQUIRED_IMAGE_PARS = []


class Component(ComponentBase):
    """
        Extends base class for general Python components. Initializes the CommonInterface
        and performs configuration validation.

        For easier debugging the data folder is picked up by default from `../data` path,
        relative to working directory.

        If `debug` parameter is present in the `config_personal.json`, the default logger is set to verbose DEBUG mode.
    """

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
        folder = params.get(KEY_FOLDER, "/")
        mask = params.get(KEY_MASK, "*")

        client = self.get_client()
        logging.info(f"Component will download files from folder: {folder} with mask: {mask}")
        client.download_files(folder_path=folder, file_mask=mask, output_dir=self.files_out_path)

    def get_client(self):
        if self.authorized_for == "personal OD":
            client = OneDriveClient(refresh_token=self.refresh_token, files_out_folder=self.files_out_path,
                                    client_id=self.client_id, client_secret=self.client_secret)
        else:
            tenant_id = self.configuration.parameters.get(KEY_TENANT_ID)
            site_name = self.configuration.parameters.get(KEY_SITE_NAME)
            logging.info(f"Site name set to {site_name}")

            client = OneDriveBusinessClient(refresh_token=self.refresh_token,
                                            files_out_folder=self.files_out_path,
                                            client_id=self.client_id,
                                            client_secret=self.client_secret,
                                            tenant_id=tenant_id,
                                            site_name=site_name)
        return client


"""
        Main entrypoint
"""
if __name__ == "__main__":
    try:
        comp = Component()
        # this triggers the run method by default and is controlled by the configuration.action parameter
        comp.execute_action()
    except UserException as exc:
        logging.exception(exc)
        exit(1)
    except Exception as exc:
        logging.exception(exc)
        exit(2)
