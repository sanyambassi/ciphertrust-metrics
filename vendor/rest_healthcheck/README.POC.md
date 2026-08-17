# REST healthcheck (vendored)

Copy of the CipherTrust REST healthcheck used by Metrics when
`HEALTHCHECK_ENGINE=rest` or the Healthcheck UI selects **rest**.

- Wired via `cm_metrics/healthcheck_runner.py` (`_run_rest_job`).
- Default remains **ksctl**; REST does not replace the ksctl vendor tree.
- Source skill (do not edit for Metrics fixes unless intentionally promoting):
  `../ciphertrust-skills/ciphertrust-healthcheck/`.

Local POC launcher (optional): `_poc_rest_hc.py` (gitignored).
