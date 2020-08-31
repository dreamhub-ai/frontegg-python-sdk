"""Flask extension that proxies requests to Frontegg."""

import os
import typing
from urllib.parse import urljoin, urlparse

import requests
from flask import (Blueprint, Flask, Request, current_app, make_response,
                   request)
from werkzeug.datastructures import Headers

from frontegg._mixins import AuditsClientMixin
from frontegg.client import BaseFronteggClient
from frontegg.permissions import ForbiddenRequest


class FronteggFlaskClient(BaseFronteggClient[Request]):
    @property
    def current_request(self) -> Request:
        return request

    @property
    def base_url(self) -> str:
        return current_app.config['FRONTEGG_API_GATEWAY_URL']

    @property
    def authentication_service_url(self):
        return current_app.config['FRONTEGG_AUTHENTICATION_SERVICE_URL']

    def proxy_request(self, endpoint: str) -> requests.Response:
        """Proxy a request from the client to Frontegg's API.

        :param endpoint: The endpoint to perform the request to.
        :return: The response of the request.
        :raises requests.HTTPError: If the Frontegg API responds with an HTTP error code, this exception is raised.
        """

        o = urlparse(request.base_url)
        hostname = o.hostname

        print('hostname for the request - ', hostname)

        requestJson = None
        if (request.is_json == True and request.data != b''):
            requestJson = request.json
        return self.request(endpoint, request.method, json=requestJson, params=request.args, host=hostname)


class Frontegg(AuditsClientMixin):
    """Frontegg Flask Extension.

    >>> from flask import Flask
    >>> app.config['FRONTEGG_CLIENT_ID'] = '00000000-0000-0000-0000-000000000000'
    >>> app.config['FRONTEGG_API_KEY'] = 'api-key'
    >>> app.config['FRONTEGG_CONTEXT_RESOLVER'] = lambda: ('me@example.com', 'tenant-id')
    >>> app = Flask(__name__)
    >>> frontegg = Frontegg(app)
    """

    def __init__(self, app: typing.Optional[Flask] = None):
        """Initialize the Frontegg extension.

        If an app is provided, then the extension is registered to the app.
        Otherwise, call :meth:`frontegg.Frontegg.init_app`.

        :param app: The flask application to extend.
        """
        try:
            client_id = app.config['FRONTEGG_CLIENT_ID']
            api_key = app.config['FRONTEGG_API_KEY']
            context_callback = app.config['FRONTEGG_CONTEXT_RESOLVER']
        except KeyError as e:
            raise ValueError(
                "{} must be specified in the application's configuration.".format(e))

        self._client = FronteggFlaskClient(
            client_id, api_key, context_callback)

        if app is not None:
            self.init_app(app)

    @property
    def _config(self) -> dict:
        """The current flask app's configuration"""
        return current_app.config

    def init_app(self, app: Flask) -> None:
        """Initialize the extension for the app.

        :param app: The flask application to extend.
        """
        frontegg_api_gateway_url = os.environ.get(
            'FRONTEGG_API_GATEWAY_URL', 'https://api.frontegg.com/')
        app.config.setdefault('FRONTEGG_API_GATEWAY_URL',
                              frontegg_api_gateway_url)

        frontegg_authentication_service_url = os.environ.get('FRONTEGG_AUTHENTICATION_SERVICE_URL',
                                                             urljoin(frontegg_api_gateway_url,
                                                                     '/vendors/auth/token'))
        app.config.setdefault(
            'FRONTEGG_AUTHENTICATION_SERVICE_URL', frontegg_authentication_service_url)

        frontegg_audits_service_url = os.environ.get('FRONTEGG_AUDITS_SERVICE_URL',
                                                     urljoin(frontegg_api_gateway_url,
                                                             '/audits'))
        app.config.setdefault('FRONTEGG_AUDITS_SERVICE_URL',
                              frontegg_audits_service_url)

        frontegg_metadata_service_url = os.environ.get('FRONTEGG_METADATA_SERVICE_URL',
                                                       urljoin(frontegg_api_gateway_url,
                                                               '/metadata'))
        app.config.setdefault('FRONTEGG_METADATA_SERVICE_URL',
                              frontegg_metadata_service_url)

        frontegg_team_service_url = os.environ.get('FRONTEGG_TEAM_SERVICE_URL',
                                                   urljoin(frontegg_api_gateway_url,
                                                           '/team'))
        app.config.setdefault('FRONTEGG_TEAM_SERVICE_URL',
                              frontegg_team_service_url)

        frontegg_blueprint = Blueprint(
            'frontegg', __name__, url_prefix='/frontegg')

        @app.route('/frontegg/identity/resources/auth/v1/user')
        def user():
            return 'Hello, World'

        @app.route('/frontegg/identity/resources/auth/v1/user/token/refresh')
        def tokenRefresh():
            return 'Hello, World'

        @app.route('/frontegg/identity/resources/auth/v1/user/saml/postlogin')
        def post_login():
            return 'Hello, World'

        @app.route('/frontegg/identity/resources/auth/v1/user/mfa/verify')
        def mfa_verify():
            return 'Hello, World'

        @frontegg_blueprint.route('/<path:endpoint>',
                                  methods=('GET', 'POST', 'PUT', 'DELETE', 'PATCH'))
        def proxy(endpoint):
            proxy_response = self._client.proxy_request(endpoint)

            try:
                response = make_response(
                    proxy_response.content, proxy_response.status_code)
                # response_headers = {
                #     **response.headers,
                #     **{key.title(): value for key, value in proxy_response.headers.items()}
                # }
                response.headers = Headers(response.headers)
                return response
            except ForbiddenRequest:
                return {'message': "Forbidden"}, 403

        app.register_blueprint(frontegg_blueprint)


__all__ = ('Frontegg',)