$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$line=[Console]::ReadLine()
if($null -eq $line -or $line.Length -gt 65536){throw 'missing/bounded parent binding'}
$b=$line | ConvertFrom-Json
function Need($ok,$why){if(-not $ok){throw $why}}
function SamePath($a,$c){[String]::Equals([string]$a,[string]$c,[StringComparison]::OrdinalIgnoreCase)}
function Sha($p){$h=[Security.Cryptography.SHA256]::Create();try{([BitConverter]::ToString($h.ComputeHash([IO.File]::ReadAllBytes($p)))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}}
$invokeStarted=$false
try {
 Need ($b.kind -eq 'owned-uia-binding' -and $b.runtime.enabled -eq $true -and $b.runtime.rootReviewed -eq $true) 'parent scope denied'
 Need ($b.runtime.powershellVersion -eq $PSVersionTable.PSVersion.ToString()) 'PowerShell version changed'
 Need ($b.runtime.dotnetVersion -eq [Environment]::Version.ToString()) 'actual .NET version changed'
 foreach($name in @('UIAutomationTypes','UIAutomationClient')) {
  $r=$b.runtime.assemblies.$name;Need ((Sha $r.path) -eq $r.sha256) 'assembly bytes changed'
  $a=[Reflection.Assembly]::LoadFrom($r.path);Need (SamePath $a.Location $r.path) 'loaded assembly path changed'
 }
 Need (SamePath ([object].Assembly.Location) $b.runtime.assemblies.mscorlib.path) 'mscorlib path changed'
 Need (SamePath ([System.Management.Automation.PSObject].Assembly.Location) $b.runtime.assemblies.'System.Management.Automation'.path) 'PowerShell assembly path changed'
 $allowed=@{};foreach($i in $b.allowed){$allowed[[int]$i.pid]=$i}
 function Owner($id){
  Need ($allowed.ContainsKey([int]$id)) 'foreign UIA provider process'
  $x=[Diagnostics.Process]::GetProcessById([int]$id)
  try{Need (([long]$x.StartTime.ToUniversalTime().ToFileTimeUtc()) -eq ([long]$allowed[[int]$id].created)) 'UIA provider birth changed'}finally{$x.Dispose()}
 }
 Owner $b.owner.pid
 $root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]([long]$b.hwnd))
 Need ($root.Current.NativeWindowHandle -eq [int]$b.hwnd -and $root.Current.ProcessId -eq [int]$b.owner.pid) 'UIA root mismatch'
 foreach($key in @('clr','UIAutomationCore')) {
  $modules=@([Diagnostics.Process]::GetCurrentProcess().Modules | Where-Object { $_.ModuleName -ieq ($key+'.dll') })
  Need ($modules.Count -eq 1 -and (SamePath $modules[0].FileName $b.runtime.nativeImages.$key.path)) 'loaded native runtime path changed'
  Need ((Sha $modules[0].FileName) -eq $b.runtime.nativeImages.$key.sha256) 'loaded native runtime bytes changed'
 }
 $walker=[System.Windows.Automation.TreeWalker]::RawViewWalker
 $stack=New-Object 'Collections.Generic.Stack[object]';$stack.Push(@($root,-1,0));$runtimeIds=New-Object 'Collections.Generic.List[object]';$elements=New-Object 'Collections.Generic.List[object]';$rows=New-Object 'Collections.Generic.List[object]';$truncated=$false;$foreign=0
 while($stack.Count -gt 0) {
  if($rows.Count -ge 256){$truncated=$true;break}
  $item=$stack.Pop();$e=$item[0];$parent=[int]$item[1];$depth=[int]$item[2]
  $pidValue=$e.Current.ProcessId
  if(-not $allowed.ContainsKey([int]$pidValue)){$foreign++;continue}
  Owner $pidValue
  $c=$e.Current
  Need ($c.ProcessId -eq $pidValue) 'UIA provider changed'
  $name=[string]$c.Name;$aid=[string]$c.AutomationId;$class=[string]$c.ClassName;$type=[string]$c.ControlType.ProgrammaticName
  Need ($name.Length -le 256 -and $aid.Length -le 256 -and $class.Length -le 127 -and $type.Length -le 127) 'UIA property ceiling'
  $index=$rows.Count;$elements.Add($e);$runtimeIds.Add(@($e.GetRuntimeId()))
  $rows.Add(@{index=$index;parent=$parent;depth=$depth;processId=[int]$pidValue;name=$name;automationId=$aid;class=$class;controlType=$type;enabled=[bool]$c.IsEnabled;offscreen=[bool]$c.IsOffscreen;nativeHandle=[long]$c.NativeWindowHandle})
  Owner $pidValue
  if($depth -ge 16){if($null -ne $walker.GetFirstChild($e)){$truncated=$true};continue}
  $children=New-Object 'Collections.Generic.List[object]';$child=$walker.GetFirstChild($e)
  while($null -ne $child){Need ($children.Count -lt 256) 'UIA sibling ceiling';$children.Add($child);$child=$walker.GetNextSibling($child)}
  for($n=$children.Count-1;$n -ge 0;$n--){$stack.Push(@($children[$n],$index,($depth+1)))}
 }
 Owner $b.owner.pid
 $r=@{kind='owned-uia-tree';hwnd=[long]$b.hwnd;nodes=@($rows.ToArray());truncated=$truncated;foreignSkipped=$foreign;acceptance=$false;actions=0}
 $json=ConvertTo-Json -InputObject $r -Depth 10 -Compress
 Need ([Text.Encoding]::UTF8.GetByteCount($json) -le 60000) 'UIA JSON pipe ceiling'
 [Console]::WriteLine($json)
 if($b.permission -eq $false){exit 0}
 Need ($b.permission -eq $true -and -not $truncated -and $foreign -eq 0 -and $rows.Count -eq $b.layout.nodes.Count -and $rows.Count -le 256) 'permission scope denied'
 $command=[Console]::ReadLine();Need ($null -ne $command -and $command.Length -le 2048) 'missing bounded permission command'
 $permit=$command | ConvertFrom-Json
 # Parent validates the entire observed tree, current origin and owned output before this command.
 Need ($permit.kind -eq 'invoke-exact-folder-permission' -and $permit.allowIndex -eq $b.layout.allowIndex -and $permit.allowIndex -gt 0 -and $permit.allowIndex -lt $rows.Count -and $permit.outputName -ceq 'output') 'permission command denied'
 Need ($permit.sha256 -match '^[a-f0-9]{64}$') 'tree receipt absent'
 $origin=[Uri]$permit.origin;Need ($origin.Scheme -eq 'http' -and $origin.Host -eq '127.0.0.1' -and $origin.AbsolutePath -eq '/' -and $origin.Query -eq '' -and $origin.Fragment -eq '') 'origin scope denied'
 Need ($b.channel -in @('chrome','msedge') -and $b.layout.channel -ceq $b.channel) 'permission channel changed'
 $rootNames=$null
 if($b.layout.PSObject.Properties.Name -contains 'rootNames'){
  $rootNames=$b.layout.rootNames
  Need ($b.channel -ceq 'msedge' -and $rootNames -is [System.Array] -and $rootNames.Count -ge 1 -and $rootNames.Count -le 2) 'root caption scope denied'
  foreach($name in $rootNames){Need ($name -is [string] -and $name.Length -gt 0 -and $name.Length -le 256 -and -not $name.Contains('{origin}')) 'root caption bound'}
  Need ($rootNames -ccontains $b.layout.nodes[0].name) 'canonical root caption absent'
  if($rootNames.Count -eq 2){Need ($rootNames[0] -cne $rootNames[1]) 'duplicate root caption'}
 }
 $allow=[int]$b.layout.allowIndex;$deny=[int]$b.layout.denyIndex;$dialog=[int]$b.layout.dialogIndex;$destination=[int]$b.layout.destinationIndex
 foreach($index in @($allow,$deny,$dialog,$destination)){Need ($index -gt 0 -and $index -lt $rows.Count) 'permission index bound'}
 $indices=@($allow,$deny,$dialog,$destination)
 Need (@($indices | Select-Object -Unique).Count -eq 4) 'permission indices overlap'
 Need ($rows[$dialog].name -ceq 'Allow this site to edit files?' -and $rows[$dialog].class -ceq 'RootView') 'wrong permission dialog'
 Need ($rows[$destination].name -ceq ([string]$permit.origin+' will be able to edit files in output')) 'permission destination/origin mismatch'
 Need ($rows[$allow].name -ceq 'Allow' -and $rows[$allow].controlType -ceq 'ControlType.Button' -and $rows[$allow].parent -eq $rows[$deny].parent) 'wrong allow control'
 Need ($rows[$deny].name -ceq "Don't Allow" -and $rows[$deny].controlType -ceq 'ControlType.Button') 'wrong denial control'
 Need (@($b.layout.providerIndices).Count -le 4) 'provider index bound'
 foreach($index in $b.layout.providerIndices){Need ($index -gt 0 -and $index -lt $rows.Count -and $rows[$index].class -ceq 'Intermediate D3D Window') 'unknown permission provider'}
 for($n=0;$n -lt $rows.Count;$n++){
  $template=$b.layout.nodes[$n];$row=$rows[$n]
  foreach($key in @('index','parent','controlType','class','name','automationId','enabled','offscreen')){
   $wanted=$template.$key;if($key -eq 'name'){$wanted=([string]$wanted).Replace('{origin}',[string]$permit.origin)}
   if($n -eq 0 -and $key -ceq 'name' -and $null -ne $rootNames){Need ($rootNames -ccontains $row[$key]) 'reviewed root caption changed'}
   else{Need ($row[$key] -ceq $wanted) 'reviewed complete permission layout changed'}
  }
 }
 for($n=0;$n -lt $elements.Count;$n++) {
  $c=$elements[$n].Current;$old=$rows[$n];Owner $c.ProcessId
  Need (([string]::Join(',',@($elements[$n].GetRuntimeId()))) -ceq ([string]::Join(',',@($runtimeIds[$n])))) 'permission runtime identity changed'
  if($n -gt 0){Need ([System.Windows.Automation.Automation]::Compare($walker.GetParent($elements[$n]),$elements[[int]$old.parent])) 'permission ancestry changed'}
  Need ($c.ProcessId -eq $old.processId -and $c.NativeWindowHandle -eq $old.nativeHandle -and $c.Name -ceq $old.name -and $c.AutomationId -ceq $old.automationId -and $c.ClassName -ceq $old.class -and $c.ControlType.ProgrammaticName -ceq $old.controlType -and $c.IsEnabled -eq $old.enabled -and $c.IsOffscreen -eq $old.offscreen) 'permission UI changed before invocation'
  if($n -notin @($b.layout.providerIndices)){Need ($c.ProcessId -eq [int]$b.owner.pid) 'permission control process changed'}
 }
 Owner $b.owner.pid
 Need ($root.Current.NativeWindowHandle -eq [int]$b.hwnd -and $root.Current.ProcessId -eq [int]$b.owner.pid) 'permission root changed'
 $button=$elements[$allow];Need ($button.Current.IsEnabled -and -not $button.Current.IsOffscreen) 'allow unavailable'
 $pattern=$button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
 Owner $b.owner.pid
 $invokeStarted=$true
 $pattern.Invoke()
 [Console]::WriteLine((ConvertTo-Json -InputObject @{kind='owned-uia-permission-invoked';hwnd=[long]$b.hwnd;actions=1;acceptance=$false;sha256=$permit.sha256} -Compress))
} catch {
 $message=[string]$_.Exception.Message;if($message.Length -gt 2048){$message=$message.Substring(0,2048)}
 [Console]::WriteLine((ConvertTo-Json -InputObject @{kind='owned-uia-unavailable';error=$message;acceptance=$false;actions=$(if($invokeStarted){$null}else{0});invocationAttempted=$invokeStarted} -Compress))
 exit 0
}
