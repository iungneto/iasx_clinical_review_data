"""Cria os grupos das políticas de mascaramento (src/sql/access_policies.sql) e define os membros. Idempotente.

    uv run python tools/setup_access_groups.py --profile <perfil> [--app iasx-jev-api]

Membros (menor privilégio):
  iasx_raw_document_readers  → quem roda a pipeline (usuário atual), que precisa ler o PDF bruto da bronze;
  iasx_clinical_text_readers → quem roda a pipeline e o service principal do app do JEV.
Ninguém mais entra sem decisão explícita: SELECT na tabela não basta para ver o conteúdo do documento.
A associação a um grupo pode levar alguns minutos para valer em is_member().
"""

import argparse

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import iam

RAW = "iasx_raw_document_readers"
TEXT = "iasx_clinical_text_readers"


def ensure_group(w: WorkspaceClient, name: str) -> iam.Group:
    found = list(w.groups.list(filter=f'displayName eq "{name}"', attributes="id,displayName,members"))
    return w.groups.get(found[0].id) if found else w.groups.create(display_name=name)


def ensure_members(w: WorkspaceClient, group: iam.Group, member_ids: list[str]) -> None:
    current = {m.value for m in group.members or []}
    missing = [m for m in member_ids if m not in current]
    if missing:
        w.groups.patch(
            group.id,
            operations=[iam.Patch(op=iam.PatchOp.ADD, path="members", value=[{"value": m} for m in missing])],
            schemas=[iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP],
        )
    print(f"{group.display_name}: {len(current) + len(missing)} membros ({len(missing)} adicionados)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--app", default="iasx-jev-api", help="Databricks App cujo service principal lê o texto")
    args = parser.parse_args()

    w = WorkspaceClient(profile=args.profile)
    pipeline_runner = w.current_user.me().id
    app_sp = str(w.apps.get(args.app).service_principal_id)

    ensure_members(w, ensure_group(w, RAW), [pipeline_runner])
    ensure_members(w, ensure_group(w, TEXT), [pipeline_runner, app_sp])


if __name__ == "__main__":
    main()
