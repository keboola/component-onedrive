import logging

from keboola.component.base import ComponentBase
from keboola.component.exceptions import UserException

from client.SharePointClient import SharePointClient
from client.OneDriveClient import OneDriveClient

# configuration variables
KEY_CLIENT_ID = 'client_id'
KEY_CLIENT_SECRET = '#client_secret'
KEY_TENANT_ID = 'tenant_id'
KEY_USER_ID = 'user_id'
KEY_SITE_URL = 'site_url'

# list of mandatory parameters => if some is missing,
# component will fail with readable message on initialization.
REQUIRED_PARAMETERS = [KEY_TENANT_ID]
REQUIRED_IMAGE_PARS = []


class Component(ComponentBase):
    """
        Extends base class for general Python components. Initializes the CommonInterface
        and performs configuration validation.

        For easier debugging the data folder is picked up by default from `../data` path,
        relative to working directory.

        If `debug` parameter is present in the `config.json`, the default logger is set to verbose DEBUG mode.
    """

    def __init__(self):
        super().__init__()

    def run(self):

        self.validate_configuration_parameters(REQUIRED_PARAMETERS)
        self.validate_image_parameters(REQUIRED_IMAGE_PARS)
        params = self.configuration.parameters

        client_id = params.get(KEY_CLIENT_ID)
        client_secret = params.get(KEY_CLIENT_SECRET)
        tenant_id = params.get(KEY_TENANT_ID)

        user_id = params.get(KEY_USER_ID, None)
        site_url = params.get(KEY_SITE_URL, None)

        if user_id:
            client = OneDriveClient(client_id, client_secret, user_id)
        elif site_url:
            client = SharePointClient(client_id, client_secret, tenant_id, site_url)
        else:
            raise UserException("user_id or site_url must be specified in config")


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
