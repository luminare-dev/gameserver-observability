# Secret placeholders in documentation

Documentation may show where a secret goes, never a real one. The secret scan (`.gitleaks.toml`)
must stay clean on this file; `tests/test_repo_config.py` checks that, and the `secrets /
gitleaks` CI job scans it with every commit.

```cfg
sv_licenseKey "YOUR_LICENSE_KEY_HERE"
sv_licenseKey cfxk_xxxxxxxxxxxx_xxxxxx
sv_licenseKey "{{ fxserver_license_key }}"
sv_licenseKey ${SV_LICENSE_KEY}
sv_licenseKey "example_license_key_value"
```

```sh
TXHOST_API_TOKEN=your-api-token-goes-here
TXHOST_API_TOKEN=disabled
TXHOST_API_TOKEN="{{ txadmin_api_token }}"
TXHOST_API_TOKEN=placeholder-token-value
```
