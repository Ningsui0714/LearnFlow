import { ArrowUpRight, Focus, FolderKanban, RefreshCw } from "lucide-react";
import Link from "next/link";
import {
  workspaceSkillDefinitions,
  workspaceSkillHref,
  type WorkspaceSkillContext,
  type WorkspaceSkillId,
} from "@/lib/skills/workspace";

const skillIcons: Record<WorkspaceSkillId, typeof RefreshCw> = {
  "snapshot-iteration": RefreshCw,
  "node-deepening": Focus,
  "workspace-instantiation": FolderKanban,
};

export default function WorkspaceSkillLauncher({
  context,
  onLaunch,
}: {
  context: WorkspaceSkillContext;
  onLaunch?: (skillId: WorkspaceSkillId) => void;
}) {
  return (
    <nav className="chat-skill-launcher" aria-label="当前岗位可用技能">
      {workspaceSkillDefinitions.map((skill) => {
        const Icon = skillIcons[skill.id];
        const available = Boolean(context.snapshotId);
        const className = `chat-skill-card ${skill.id}${available ? "" : " disabled"}`;
        const content = <>
          <i><Icon size={14} /></i>
          <span>
            <b>{skill.label}</b>
            <small>{skill.description}</small>
          </span>
          <ArrowUpRight size={12} />
        </>;
        return onLaunch ? (
          <button
            type="button"
            className={className}
            data-testid={`workspace-skill-${skill.id}`}
            disabled={!available}
            onClick={() => onLaunch(skill.id)}
            key={skill.id}
            aria-label={`在当前工作台启动${skill.label}技能`}
          >
            {content}
          </button>
        ) : (
          <Link
            className={className}
            data-testid={`workspace-skill-${skill.id}`}
            href={workspaceSkillHref(skill.id, context)}
            aria-disabled={!available}
            onClick={(event) => { if (!available) event.preventDefault(); }}
            key={skill.id}
            aria-label={`启动${skill.label}技能`}
          >
            {content}
          </Link>
        );
      })}
    </nav>
  );
}
