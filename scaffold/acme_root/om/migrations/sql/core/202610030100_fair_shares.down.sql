-- Takes the fair shares back out: the fence, then the table.

DROP POLICY tenant_fence ON core.fair_shares;
DROP TABLE core.fair_shares;
