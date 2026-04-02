import {NavButton, IconButton} from "./Buttons.jsx";
import {useContext, useState} from "react";
import { ViewContext } from "../pages/Buckaroo.jsx";
import SettingsModal from "./SettingsModal.jsx";
import { resetApp } from "../utils/serverCalls.jsx";
import "../styles/Header.css"

export default function Header( { onReset} ) {
  onReset = onReset || (() => {});
  return (
    <div id="header" className="header">
      <h1 onClick={ onReset }>
        Buckaroo Visual Wrangler{" "}
        <img
          src="/images/favicon/favicon-96x96.png"
          height="40"
          alt="Buckaroo Logo"
        />
      </h1>
    </div>
  );
}

export function BuckarooHeader( { onReset} ) {
    onReset = onReset || (() => {});
    const { activeView, setActiveView } = useContext(ViewContext);
    const [settingsOpen, setSettingsOpen] = useState(false);

    const handleBack = async () => {
        await resetApp();
        onReset();
    };

    return (
        <div id="header">
            <h1 onClick={ onReset }>
                Buckaroo Visual Wrangler{" "}
                <img
                    src="/images/favicon/favicon-96x96.png"
                    height="24"
                    alt="Buckaroo Logo"
                />
            </h1>
            <div className="navButtonContainer">
                <NavButton onClick={() => setActiveView('plots')} isSelected={activeView === 'plots'}>Plots</NavButton>
                <NavButton onClick={() => setActiveView('graph')} isSelected={activeView === 'graph'}>Provenance Graph</NavButton>
            </div>
            <div className="headerActions">
                <IconButton onClick={() => setSettingsOpen(true)} title="Settings">&#9881;</IconButton>
                <IconButton onClick={handleBack} title="Home">&#8962;</IconButton>
            </div>
            <SettingsModal visible={settingsOpen} onClose={() => setSettingsOpen(false)} />
        </div>
    );
}
