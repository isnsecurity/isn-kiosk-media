import json
import ssl
from six.moves import urllib


class RestClient:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.token = None

    def inject_token(self, token):
        self.token = token

    def send(self, data, verify_ssl=True):
        headers = {'Accept': 'application/json',
                   'Content-Type': 'application/json'}

        if self.token is not None:
            headers['Authorization'] = 'Bearer {}'.format(self.token)

        req = urllib.request.Request(
            self.endpoint, json.dumps(data).encode('utf-8'), headers)

        try:
            context = ssl.create_default_context(
            ) if verify_ssl else ssl._create_unverified_context()
            response = urllib.request.urlopen(req, context=context)
            return response.read().decode('utf-8')
        except urllib.error.HTTPError as ex:
            print((ex.read()))
            print('')
            raise ex
