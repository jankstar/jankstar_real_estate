"""
Migration: carry over each contract's contractual partner into the party
assignment list (real_estate.contract.party) as 'Main Tenant'.

For every real_estate.contract record in the system (regardless of state,
including already inactive/terminated contracts), this checks whether a
party assignment with party = contract.contractual_partner, role
'Main Tenant' and valid_from = contract.start_date already exists. If not,
it is created.

The 'Main Tenant' role is looked up by its sequence (=10, see
contract_party.xml), not by name - more robust against translations. It
must already exist in the target database (e.g. via a prior
trytond-admin -u real_estate with the default roles shipped in
contract_party.xml).

The script is idempotent: a repeated run does not create duplicate
assignments (checked via party + contract + role + valid_from, identical
to the unique constraint on real_estate.contract.party).

Usage:
    python tests/migrate_contract_main_tenant.py --database <database_name> [--config <trytond.conf>]
"""

import argparse

from proteus import Model, config

MAIN_TENANT_ROLE_SEQUENCE = 10


def connect(database: str, cfg_file: str | None):
    if cfg_file:
        return config.set_trytond(database=database, config_file=cfg_file)
    return config.set_trytond(database=database)


def get_main_tenant_role():
    Role = Model.get('real_estate.contract.party.role')
    results = Role.find([('sequence', '=', MAIN_TENANT_ROLE_SEQUENCE)])
    return results[0] if results else None


def has_existing_assignment(contract, role) -> bool:
    ContractParty = Model.get('real_estate.contract.party')
    return bool(ContractParty.find([
        ('contract', '=', contract.id),
        ('party', '=', contract.contractual_partner.id),
        ('role', '=', role.id),
        ('valid_from', '=', contract.start_date),
    ]))


def assign_main_tenant(contract, role) -> None:
    ContractParty = Model.get('real_estate.contract.party')
    cp = ContractParty()
    cp.contract = contract
    cp.party = contract.contractual_partner
    cp.role = role
    cp.valid_from = contract.start_date
    cp.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, help='Tryton database name')
    parser.add_argument('--config', default=None, help='Path to trytond.conf')
    args = parser.parse_args()

    cfg = connect(args.database, args.config)

    role = get_main_tenant_role()
    if role is None:
        print(
            f'Role "Main Tenant" (sequence={MAIN_TENANT_ROLE_SEQUENCE}) not '
            f'found. Please run trytond-admin -u real_estate first (see '
            f'contract_party.xml). Aborting.'
        )
        return

    Contract = Model.get('real_estate.contract')
    # active_test=False: also include already inactive (e.g. soft-deleted)
    # contracts, not just the actively filtered subset.
    with cfg.set_context(active_test=False):
        contracts = Contract.find([])

    created = 0
    skipped = 0
    for contract in contracts:
        if not contract.contractual_partner or not contract.start_date:
            print(
                f'  Skipped (no partner/start date): '
                f'{contract.rec_name} (id={contract.id})'
            )
            skipped += 1
            continue
        if has_existing_assignment(contract, role):
            skipped += 1
            continue
        assign_main_tenant(contract, role)
        print(
            f'  Main tenant assigned: {contract.rec_name} (id={contract.id})'
            f' — {contract.contractual_partner.name}'
            f' from {contract.start_date}'
        )
        created += 1

    print(
        f'Done. {created} party assignment(s) created, '
        f'{skipped} skipped (already existing or missing partner/start date).'
    )


if __name__ == '__main__':
    main()
