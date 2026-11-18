use super::*;
use group_metadata::ClonedGroup;

fn owner(parent: &Group, workspace: &Arc<Workspace>) -> Result<ClonedGroup> {
    ClonedGroup::build(
        parent,
        Reservation::for_workspace(workspace.clone()),
        |group| group,
    )
}

pub(super) fn run(parent: &Group, ctx: &Context) -> Result<serde_json::Value> {
    let fields = vec!["界\n\"escaped".repeat(5), String::new()];
    let columns = [0, 1, 0];
    let entry = Entry::values(9, FieldViews::owned(&fields), &columns);
    let workspace = Arc::new(Workspace::new(1024 * 1024));
    let mut probe = owner(parent, &workspace)?;
    probe.append(&Entry::part(8, 1), ctx)?;
    probe.append(&entry, ctx)?;
    let expected = probe.group.lineage.clone();
    let peak = workspace.peak() as usize;
    let retained = workspace.used();
    ensure!(
        retained == probe.group.json_capacity()? as u64 && peak > retained as usize,
        "mutable lineage missed growth overlap"
    );
    drop(probe);
    for shared in [false, true] {
        for limit in [peak - 1, peak, peak + 1] {
            let pool = Arc::new(MemoryPool::new(if shared {
                limit as u64
            } else {
                u64::MAX
            }));
            let workspace = Arc::new(if shared {
                Workspace::shared(2 * peak, pool.clone())
            } else {
                Workspace::new(limit)
            });
            let mut probe = owner(parent, &workspace)?;
            probe.append(&Entry::part(8, 1), ctx)?;
            let before = probe.group.lineage.clone();
            let result = probe.append(&entry, ctx);
            if limit < peak {
                let error = result.err().context("growth edge accepted")?;
                ensure!(
                    matches!(
                        (shared, error.downcast_ref::<MemoryAdmission>()),
                        (true, Some(MemoryAdmission::Shared { .. }))
                            | (false, Some(MemoryAdmission::Local))
                    ),
                    "growth denial lost type"
                );
                ensure!(
                    probe.group.lineage == before,
                    "denied growth changed live tree"
                );
            } else {
                result?;
                ensure!(probe.group.lineage == expected, "growth changed tree");
                probe.truncate(parent.lineage.len())?;
                ensure!(
                    probe.group.lineage == parent.lineage
                        && workspace.used() == probe.group.json_capacity()? as u64,
                    "truncate released retained vector or retained removed payload"
                );
                probe.append(&Entry::part(8, 2), ctx)?;
                ensure!(
                    workspace.used() == probe.group.json_capacity()? as u64,
                    "regrowth charge changed"
                );
            }
            drop(probe);
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "growth edge leaked"
            );
        }
    }
    let workspace = Arc::new(Workspace::new(4 * peak));
    let mut probe = owner(parent, &workspace)?;
    probe.append(&entry, ctx)?;
    let leaf = owner(&probe.group, &workspace)?;
    let expected = leaf.group.lineage.clone();
    probe.truncate(parent.lineage.len())?;
    drop(probe);
    ensure!(
        leaf.group.lineage == expected && workspace.used() == leaf.group.json_capacity()? as u64,
        "source truncate/drop changed independent leaf"
    );
    drop(leaf);
    ensure!(workspace.used() == 0, "independent leaf leaked");
    Ok(
        json!({"local_shared_edge_checks":6,"growth_overlap":true,"construction_peak_bytes":peak,
        "retained_bytes":retained,"denied_tree_unchanged":true,"truncate_and_regrowth":true,
        "independent_leaf_survives_source_mutation_and_drop":true,"final_reserved_bytes":0}),
    )
}
