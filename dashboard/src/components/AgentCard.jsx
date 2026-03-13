export default function AgentCard({ agent, onSelect }) {
  const isOnline = agent.status === "online";

  return (
    <div
      onClick={() => onSelect(agent)}
      className="cursor-pointer rounded-lg border border-slate-700 bg-slate-800 p-4 hover:border-indigo-500 transition-colors"
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-lg font-semibold text-white">{agent.name}</h3>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
            isOnline
              ? "bg-emerald-500/10 text-emerald-400"
              : "bg-red-500/10 text-red-400"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              isOnline ? "bg-emerald-400" : "bg-red-400"
            }`}
          />
          {agent.status}
        </span>
      </div>

      <p className="text-sm text-slate-400 mb-3 line-clamp-2">
        {agent.description}
      </p>

      {agent.skills?.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {agent.skills.map((skill) => (
            <span
              key={skill.id}
              className="rounded-md bg-slate-700 px-2 py-0.5 text-xs text-slate-300"
            >
              {skill.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
