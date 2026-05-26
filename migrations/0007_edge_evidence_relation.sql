-- 0007_edge_evidence_relation.sql
--
-- Preserve the original source relationship label for derived edges. For
-- example, inbound-index ``related_genre`` edges can retain that their evidence
-- came from ``subclass_of``, ``part_of``, or another upstream relation.

begin;

alter table wg_edges
    add column if not exists evidence_relation text;

commit;
