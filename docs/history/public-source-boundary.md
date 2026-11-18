# Public source and historical evidence boundary

The 0.2 public repository is a clean import of the full maintained Chopper source
snapshot, including native and hosted engine adapters, UI, scripts, documentation
and attributed vendor sources. Its Git history starts at that reviewed import.
The previous repository remains a private archive; its commits, pull requests,
discussion revisions, Actions artifacts and historical release binaries are not
part of the public Git history. Public author metadata uses the approved noreply
identity. Selected open issues are curated for migration with an explicit old/new
mapping; a historical issue number alone does not identify a new public issue.

Historical commit and tree IDs retained in documentation identify the original
inspected sources. They are provenance references, not a promise that the clean
public repository contains those Git objects. Existing validation remains bounded
to its recorded source, build, workload and platform. A clean import or an editorial
privacy change does not recertify a runtime or establish fresh release acceptance.
New public binaries need their own reviewed build provenance and acceptance.

Maintained examples and synthetic tests use neutral paths. Some historical source
and receipt locators in maintained prose are explicitly marked as sanitized
aliases. In particular, the published focused639 campaign lineage locator is
`/opt/chopper/private-acceptance/focused639-linux-lineage-seal/lineage.json`.
It is a neutral published alias, not the original sealed workstation locator or
a newly qualified runtime. The original sealed locator, exact source and records
remain privately retained. The campaign's cryptographic pins and strict exact-path,
content, source and lifetime checks remain required. The disabled example is not
execution approval; placing a file at the alias does not qualify a new campaign
or make the old sealed records portable. Changed paths inside sealed records still
fail the existing checks.

Raw historical evidence must retain its original bytes and hashes in private
custody when it contains restricted locators. Public navigation may resolve an
archived-original alias through the [evidence storage contract](../evidence-storage.md).
Such an alias is not a redacted original, a replacement measurement, or evidence
that a historical runtime ran under the published neutral path. Public derivatives,
where provided, have separate identities and an explicit provenance mapping.
Private originals and failed attempts remain subject to their recorded access
boundary; privacy cleanup must not silently relabel them or erase failures.
