param([Parameter(Mandatory=$true)][string]$SourceBase64)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$text=[Text.UTF8Encoding]::new($false,$true).GetString([Convert]::FromBase64String($SourceBase64))
$null=[System.Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
if($errors.Count -ne 0){throw ($errors | Out-String)}
[Console]::WriteLine('{"status":"passed","sourceExecuted":false}')
