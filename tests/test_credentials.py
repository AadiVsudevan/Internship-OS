"""Credential parser regressions use synthetic data, never real private keys."""
import json
import pytest
from src.credentials import parse_service_account, CredentialConfigurationError
from run_personal import sheet_profile
from unittest.mock import Mock

KEY={'type':'service_account','client_email':'test@example.invalid','private_key':'synthetic-not-a-key','token_uri':'https://oauth2.googleapis.com/token'}

@pytest.mark.parametrize('raw',[json.dumps(KEY), '\ufeff'+json.dumps(KEY), json.dumps(json.dumps(KEY))])
def test_complete_and_once_encoded_json(raw):
    assert parse_service_account(raw)==KEY

@pytest.mark.parametrize('raw',['"type": "service_account", "private_key": "DO_NOT_EXPOSE"', '123456abcdef', '[]', 'null', '42', '{"secret":"DO_NOT_EXPOSE"}'])
def test_bad_input_has_safe_actionable_error(raw):
    with pytest.raises(CredentialConfigurationError) as e:
        parse_service_account(raw)
    assert 'GOOGLE_SERVICE_ACCOUNT_JSON' in str(e.value)
    assert 'DO_NOT_EXPOSE' not in str(e.value)


def test_missing_key_fields_rejected():
    with pytest.raises(CredentialConfigurationError,match='incomplete'):
        parse_service_account('{"type":"service_account"}')

@pytest.mark.parametrize('value',['"finance": "research"','{}'])
def test_profile_error_identifies_cell_not_secret(value):
    store=Mock();store.load.return_value=[{'Key':'interests','Value':value}]
    with pytest.raises(ValueError,match='Profile tab: interests'):
        sheet_profile(store)
