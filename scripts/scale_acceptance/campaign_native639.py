"""Immutable selected-native639 campaign identities, not reusable policy defaults.

Keep these recorded values with the frozen release. A new campaign needs its own
reviewed record and fresh qualification; never rewrite these pins to admit it.
The published absolute lineage locator is a sanitized alias, not host discovery
or a newly qualified runtime. The original sealed locator and source remain
privately retained; see docs/history/public-source-boundary.md. Cryptographic
pins and exact locator checks remain required.
"""
PRODUCT = '639d1fe97d985b1544df0932321c6a93cca2567b'
TREE = 'b3bde79d552ee29760cb283d07938f9248cee0bb'
PACKAGE_RECEIPT = '1720f28a01cbbd7a30cbb8c8614b9efc2da01e57c765c625f51e8a5e3455c30d'
BUILD = 'feb9e099e5e0f22c4da8d0f5ba7269e221c91e9d'
BUILD_TREE = '57f6675f4e216d0b504c3063c17a2b37ab16ac20'
RECONCILIATION = 'a5034cab5d27c3244aec4d08637f62afa0382faeaa43afc63ca59ba317da90f8'
PACKAGING_DELTA = {'docs/release-packaging.md', 'docs/releases/native-usage.txt',
                   'scripts/package-release.py'}
LINEAGE_PATH = '/opt/chopper/private-acceptance/focused639-linux-lineage-seal/lineage.json'
LINEAGE_SHA = '19289b1e120b26610e2df0f4f7a62ed336aeedb2ad132f4b8e3435c3f16996d2'
LINUX_SCALE_PLAN_SHA = '4beb2941b38de4bdb2a39b62b18245b8710e4fa3e8fe4e11e8f705afd1a1e695'
LINUX_SCALE_REPORTS = {'D':'17bd91e5360003f7b4ecf41a2a33f18a08d71eebb8e248c4f0f6f8bf6b23b1ad',
    'G':'25587c74b4ed9548ef675b1abfb39dff40b90a9df58cb81cfd17613600570796'}
