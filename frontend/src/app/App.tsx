import { MOBILE_QUERY, useMediaQuery } from "@/hooks";
import { Header } from "./Header";
import { MobileWorkspace, useMobilePanel, useWorkspace, Workspace } from "./Workspace";
import "./app.css";

export default function App() {
  const mobile = useMediaQuery(MOBILE_QUERY);
  const workspace = useWorkspace();
  const [active, setActive] = useMobilePanel();

  return (
    <div className="app">
      <Header
        compact={mobile}
        active={active}
        onAdd={mobile ? setActive : workspace.addPanel}
        onResetLayout={workspace.resetLayout}
      />
      <main className="app-main">
        {mobile ? <MobileWorkspace active={active} /> : <Workspace workspace={workspace} />}
      </main>
    </div>
  );
}
