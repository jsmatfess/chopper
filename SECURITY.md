# Reporting a security issue

Use [GitHub private vulnerability reporting](https://github.com/jsmatfess/chopper/security/advisories/new) for suspected security vulnerabilities. Include the Chopper version, operating system or browser, reproduction steps and the smallest synthetic input that demonstrates the issue.

Do not post credentials, personal CSV data, private file paths or unredacted logs in a public issue. Ordinary bugs and feature requests belong in [GitHub Issues](https://github.com/jsmatfess/chopper/issues).

## Processing boundaries

The Chopper CLI reads local files. The hosted app processes files in a browser worker and uses browser storage; it does not upload CSV contents to the hosted site. Exported files and manifests can contain input values and job configuration, so review them before sharing.

Working-memory reservations are not a complete process or browser RSS cap. Browser completion requires the verified completion marker; partial exports without it are not successful results. See the [behavior specification](docs/specification.md), [browser requirements](docs/browser.md) and the release notes matching your version for supported limits.
