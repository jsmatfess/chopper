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
with file and folder access enabled. Your CSV is processed locally in your
browser. [Try a sample export](../browser.md#try-a-sample-export) to practice
with synthetic data and check the results.

Chopper detects CSV settings when you select a file and uses them to load
the input preview. Review the columns before running. You can edit the
input settings or repeat detection under **Parsing, encoding & ZIP member**. See
[supported CSV settings](../job-json.md#csv-settings).

- [Choose an output folder and recover from a blocked selection](../browser.md#choosing-an-output-folder).
- [Verify an export or recover after an interruption](../browser.md#checking-a-hosted-export-after-interruption).

## Choose a recipe by outcome

- [Keep each upload under a limit](../job-recipes.md#make-upload-sized-chunks)
  with a maximum row count or CSV size.
- [Make exactly N files](../job-recipes.md#make-exactly-n-files) with an even
  split that keeps rows in order.
- [Make one set per country](../job-recipes.md#partition-by-a-business-column)
  by routing each row according to its country column.

## Save, automate, and verify Jobs

| I want to… | Guide |
| --- | --- |
| Check which CSV encodings and dialect options are supported | [CSV settings](../job-json.md#csv-settings) |
| Find commands and flags for the installed version | [CLI reference](../cli-reference.md) |
| Write a saved Job and get editor completions | [Job JSON and schema](../job-json.md) |
| Write calculated columns and look up a function | [Formula functions](../formula-functions.md) |
| Check a saved Job before opening its input | [Validate](../validate-cli.md) |
| Schedule Runs and handle exit statuses or reports | [Run and automation](../run-cli.md) |
| Verify published CSVs or ZIP members | [Native manifest](../native-manifest.md) |

For installation, memory, disk space, or sharing diagnostics, see
[operator support](../operator-support.md). Before upgrading a saved Job or
script, check [compatibility and migration](../compatibility.md) and the
[release notes](https://github.com/jsmatfess/chopper/releases).
