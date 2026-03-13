import { useEffect, useState } from "react";
import { fetchAgents } from "../hooks/useApi";
import AgentCard from "./AgentCard";

export default function AgentPanel({ onSelectAgent }) {
  const [agents, setAgents] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = () =>
      fetchAgents()
        .then(setAgents)
        .catch((e) => setError(e.message));

    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <section>
      <h2 className="text-xl font-bold text-white mb-4">Agents</h2>
      {error && (
        <p className="text-red-400 text-sm mb-2">
          Failed to load agents: {error}
        </p>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            onSelect={onSelectAgent}
          />
        ))}
        {agents.length === 0 && !error && (
          <p className="text-slate-500 text-sm col-span-full">
            No agents registered.
          </p>
        )}
      </div>
    </section>
  );
}
