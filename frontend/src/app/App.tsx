import { Header } from "./Header";
import { useWorkspace, Workspace } from "./Workspace";
import "./app.css";

export default function App() {
  const workspace = useWorkspace();
  return (
    <div className="app">
      <Header onAdd={workspace.addPanel} onResetLayout={workspace.resetLayout} />
      <main className="app-main">
        <Workspace workspace={workspace} />
      </main>
    </div>
  );
}
