import "../../styles/Nodes.css";

/**
 * The boundary drawn around a node and its supporting sub-nodes - see supportLayout's groupBoundaries. Sized
 * from its data rather than its content, since it has none: React Flow measures the box this draws.
 */
export function SupportGroup({data}) {
    return <div className="support-group" style={{width: data.width, height: data.height}} />;
}
