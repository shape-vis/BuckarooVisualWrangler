import {NavButton} from "./Buttons.jsx";
import React, {useContext} from "react";
import { ViewContext } from "../pages/Buckaroo.jsx";
import "./Header.css"

export default function Header( { onReset} ) {
  onReset = onReset || (() => {});
  return (
    <div id="header" className="header">
      <h1 onClick={ onReset } style={{cursor: "pointer"}}>
        Buckaroo Visual Wrangler{" "}
        <img
          src="/images/favicon/favicon-96x96.png"
          style={{ verticalAlign: "middle" }}
          height="40"
          alt="Buckaroo Logo"
        />
      </h1>
    </div>
  );
}

export function BuckarooHeader( { onReset} ) {
    onReset = onReset || (() => {});
    const { setActiveView } = useContext(ViewContext);

    return (
        <div id="header">
            <h1 onClick={ onReset } style={{cursor: "pointer"}}>
                Buckaroo Visual Wrangler{" "}
                <img
                    src="/images/favicon/favicon-96x96.png"
                    style={{ verticalAlign: "middle" }}
                    height="40"
                    alt="Buckaroo Logo"
                />
            </h1>
            <div className={"navButtonContainer"}>
                <NavButton onClick={() => setActiveView('plots')}>Plots</NavButton>
                <NavButton onClick={() => setActiveView('graph')}>Provenance Graph</NavButton>
            </div>
        </div>
    );
}
