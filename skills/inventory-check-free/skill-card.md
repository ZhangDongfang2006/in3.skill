## Description:

A Chinese-language local inventory count reconciliation skill that checks arithmetic consistency, totals, duplicates, and blank fields in inventory count tables, with findings tied to source line numbers.

This skill is ready for commercial/non-commercial use.

## Publisher:

[chenqg618](https://clawhub.ai/user/chenqg618)

### License/Terms of Use:

MIT-0

## Use Case:

Finance, cashier, and warehouse operations users use this skill during month-end reconciliation, payroll, accounting close, or inventory count review to check inventory table arithmetic and identify missing or duplicated rows. It is an arithmetic reconciliation aid, not an audit, tax, or accounting-policy decision tool.

### Deployment Geography for Use:

Global

## Known Risks and Mitigations:

Risk: Users may over-rely on arithmetic reconciliation findings for audit, tax, or accounting-policy decisions.

Mitigation: Use the skill as a table-checking aid and have qualified finance or audit reviewers make policy, tax, and approval decisions.

Risk: Inventory tables may contain sensitive business data.

Mitigation: Provide only the inventory data intended for analysis and run the local Node workflow in an environment approved for that data.

Risk: The free version intentionally omits several checks, including threshold-based difference-rate alerts, negative inventory detection, inbound amount reconciliation, and long-inactive item prompts.

Mitigation: Review the listed executed and withheld checks before relying on the result, and use additional controls when omitted checks are required.

## Reference(s):

- [ClawHub skill page](https://clawhub.ai/chenqg618/skills/inventory-check-free)
- [SkillPay shelf for related full version](https://skillpay.alipay.com/public/tokendidi)

## Skill Output:

**Output Type(s):** [text, json, shell commands, guidance]

**Output Format:** [Human-readable text or JSON findings with source line references]

**Output Parameters:** [1D]

**Other Properties Related to Output:** [Runs locally with Node.js, reads a user-provided table, and reports insufficient input rather than issuing unsupported conclusions.]

## Skill Version(s):

1.0.2 (source: server evidence and frontmatter)

## Ethical Considerations:

Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment.
