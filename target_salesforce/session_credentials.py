import abc
import logging
import time
from collections import namedtuple
from dataclasses import dataclass
from typing import Union

import jwt
import requests
from simple_salesforce import SalesforceLogin

LOGGER = logging.getLogger(__name__)

OAuthCredentials = namedtuple(
    "OAuthCredentials", ("client_id", "client_secret", "refresh_token")
)

PasswordCredentials = namedtuple(
    "PasswordCredentials", ("username", "password", "security_token")
)

JWTCredentials = namedtuple(
    "JWTCredentials", ("jwt_client_id", "jwt_username", "jwt_private_key")
)


@dataclass
class Session:
    session_id: str
    instance: str = None
    instance_url: str = None


def parse_credentials(
    config: dict,
) -> Union[JWTCredentials, OAuthCredentials, PasswordCredentials]:
    for cls in (JWTCredentials, OAuthCredentials, PasswordCredentials):
        creds = cls(*(config.get(key) for key in cls._fields))
        if all(creds):
            return creds

    raise Exception(
        "Cannot create credentials from config. Target supports JWT bearer, OAuth refresh-token, "
        "and username/password authentication."
    )


class SalesforceAuth(metaclass=abc.ABCMeta):
    def __init__(self, credentials, domain):
        self.domain = domain
        self._credentials = credentials

    @abc.abstractmethod
    def login(self) -> Session:
        """Attempt to login and return Session info"""
        pass

    @classmethod
    def from_credentials(cls, credentials, **kwargs):
        if isinstance(credentials, JWTCredentials):
            return SalesforceAuthJWT(credentials, **kwargs)

        if isinstance(credentials, OAuthCredentials):
            return SalesforceAuthOAuth(credentials, **kwargs)

        if isinstance(credentials, PasswordCredentials):
            return SalesforceAuthPassword(credentials, **kwargs)

        raise Exception("Invalid credentials")


class SalesforceAuthOAuth(SalesforceAuth):
    @property
    def _login_body(self):
        return {"grant_type": "refresh_token", **self._credentials._asdict()}

    @property
    def _login_url(self):
        return f"https://{self.domain}.salesforce.com/services/oauth2/token"

    def login(self):
        try:
            LOGGER.info(f"Attempting login via OAuth2")

            resp = requests.post(
                self._login_url,
                data=self._login_body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            resp.raise_for_status()
            auth = resp.json()

            LOGGER.info("OAuth2 login successful")
            return Session(auth["access_token"], instance_url=auth["instance_url"])
        except Exception as e:
            error_message = str(e)
            if resp:
                error_message = error_message + ", Response from Salesforce: {}".format(
                    resp.text
                )
            raise Exception(error_message) from e


class SalesforceAuthPassword(SalesforceAuth):
    def login(self):
        session_id, instance = SalesforceLogin(
            domain=self.domain, **self._credentials._asdict()
        )
        return Session(session_id, instance=instance)


class SalesforceAuthJWT(SalesforceAuth):
    JWT_LIFETIME_SECONDS = 300

    @property
    def _login_url(self):
        return f"https://{self.domain}.salesforce.com/services/oauth2/token"

    @property
    def _audience(self):
        return f"https://{self.domain}.salesforce.com"

    def _build_assertion(self):
        claims = {
            "iss": self._credentials.jwt_client_id,
            "sub": self._credentials.jwt_username,
            "aud": self._audience,
            "exp": int(time.time()) + self.JWT_LIFETIME_SECONDS,
        }
        return jwt.encode(
            claims, self._credentials.jwt_private_key, algorithm="RS256"
        )

    def login(self) -> Session:
        resp = None
        try:
            LOGGER.info("Attempting login via OAuth2 JWT Bearer")
            resp = requests.post(
                self._login_url,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": self._build_assertion(),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            auth = resp.json()
            LOGGER.info("OAuth2 JWT Bearer login successful")
            return Session(auth["access_token"], instance_url=auth["instance_url"])
        except Exception as e:
            error_message = str(e)
            if resp is not None:
                error_message = f"{error_message}, Response from Salesforce: {resp.text}"
            raise Exception(error_message) from e
