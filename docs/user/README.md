# User guide

Chopper splits, partitions, shuffles, and allocates CSV rows. Choose the native
command-line tool for repeatable jobs and scripts, or open the hosted app to
configure a Job in your browser.

## Install and run the native CLI

Start with the [native quickstart](../../README.md#native-quickstart) on Windows
or Linux. Download and verify the package, then split the bundled sample and
check the output. Follow the [Job recipes](../job-recipes.md) for upload-sized
chunks, partitioning, or treatment/control allocation.

## Use Chopper in your browser

Open the [hosted app](https://chopper-1rx.pages.dev/) in desktop Chrome or Edge
with file and folder access enabled. Choose a CSV and a writable output folder,
set your pipeline and limits, then select **Run**. **Analyze** is optional.

- [Choose an output folder and recover from a blocked selection](../browser.md#choosing-an-output-folder).
- [Verify an export or recover after an interruption](../browser.md#checking-a-hosted-export-after-interruption).

## Save, automate, and verify Jobs

| I want to… | Guide |
| --- | --- |
| Find commands and flags for the installed version | [CLI reference](../cli-reference.md) |
| Write a saved Job and get editor completions | [Job JSON and schema](../job-json.md) |
| Check a saved Job before opening its input | [Validate](../validate-cli.md) |
| Schedule Runs and handle exit statuses or reports | [Run and automation](../run-cli.md) |
| Verify published CSVs or ZIP members | [Native manifest](../native-manifest.md) |

For installation, memory, disk space, or sharing diagnostics, see
[operator support](../operator-support.md). Before upgrading a saved Job or
script, check [compatibility and migration](../compatibility.md) and the
[release notes](https://github.com/jsmatfess/chopper/releases).
