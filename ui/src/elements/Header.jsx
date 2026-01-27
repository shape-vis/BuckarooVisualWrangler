

export default function Header( { onReset } ) {
  onReset = onReset || (() => {});

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
    </div>
  );
}
