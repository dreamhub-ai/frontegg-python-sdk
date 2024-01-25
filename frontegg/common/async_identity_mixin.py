import asyncio

import jwt
import os
from jwt import InvalidTokenError
from typing import Optional

from frontegg.common import FronteggAsyncAuthenticator
from frontegg.common.clients.token_resolvers.async_access_token_resolver import AccessTokenAsyncResolver
from frontegg.common.clients.token_resolvers.async_authorization_token_resolver import AuthorizationJWTAsyncResolver
from frontegg.helpers.frontegg_urls import frontegg_urls
from frontegg.helpers.logger import logger
from frontegg.helpers.retry import retry
from frontegg.common.clients.types import AuthHeaderType, IValidateTokenOptions
from frontegg.helpers.exceptions import UnauthenticatedException

jwt_decode_retry = os.environ.get('FRONTEGG_JWT_DECODE_RETRY') or '1'
jwt_decode_retry = int(jwt_decode_retry)
jwt_decode_retry_delay = os.environ.get('FRONTEGG_JWT_DECODE_RETRY_DELAY_MS') or '0'
jwt_decode_retry_delay = float(jwt_decode_retry_delay) / 1000


class IdentityAsyncClientMixin:
    __publicKey = None
    __tokenResolvers = []
    def __init__(self, async_authenticator: FronteggAsyncAuthenticator):
        self.__async_authenticator = async_authenticator
        self.__tokenResolvers = [AuthorizationJWTAsyncResolver(), AccessTokenAsyncResolver(async_authenticator)]

    async def get_public_key(self) -> str:
        if self.__publicKey:
            return self.__publicKey

        logger.info('could not find public key locally, will fetch public key')
        reties = 0
        while reties < 10:
            try:
                self.__publicKey = await self.fetch_public_key()
                return self.__publicKey
            except Exception as e:
                reties = reties + 1
                logger.error(
                    'could not get public key from frontegg, retry number - ' + str(reties) + ', ' + str(e))
                await asyncio.sleep(1)

        logger.error('failed to get public key in all retries')

    async def fetch_public_key(self) -> str:
        if self.__async_authenticator.should_refresh_vendor_token:
            await self.__async_authenticator.refresh_vendor_token()

        response = await self.__async_authenticator.vendor_session_request.get(
            frontegg_urls.identity_service['vendor_config'], timeout=3)
        response.raise_for_status()
        data = response.json()
        return data.get('publicKey')

    async def validate_identity_on_token(
            self,
            token,
            options: Optional[IValidateTokenOptions] = None,
            type=AuthHeaderType.JWT.value
    ):
        if type == AuthHeaderType.JWT.value:
            try:
                token = token.replace("Bearer ", "")
            except:
                logger.error("Failed to extract token - ", token)

        public_key = None
        try:
            public_key = await self.get_public_key()
        except:
            logger.error("Failed to get public key - ")
            raise UnauthenticatedException()

        resolver = None
        for _resolver in self.__tokenResolvers:
            if _resolver.should_handle(type) is True:
                resolver = _resolver
                break
        if not resolver:
            logger.error("Failed to find token resolver")
            raise UnauthenticatedException()

        entity = await resolver.validate_token(token, public_key, options)
        return entity

    async def decode_jwt(self, authorization_header, verify: Optional[bool] = True):
        if not authorization_header:
            raise InvalidTokenError('Authorization headers is missing')
        logger.debug('found authorization header: ' +
                     str(authorization_header))
        jwt_token = authorization_header.replace('Bearer ', '')
        public_key = await self.get_public_key()
        logger.debug('got public key' + str(public_key))
        decoded = self.__get_jwt_data(jwt_token, verify, public_key)
        logger.info('jwt was decoded successfully')
        logger.debug('JWT value - ' + str(decoded))
        return decoded

    @retry(action='decode jwt', total_tries=jwt_decode_retry, retry_delay=jwt_decode_retry_delay)
    def __get_jwt_data(self, jwt_token, verify, public_key):
        if verify:
            return jwt.decode(jwt_token, public_key, algorithms=['RS256'], options={"verify_aud": False})
        return jwt.decode(jwt_token, algorithms=['RS256'], options={"verify_aud": False, "verify_signature": verify})
