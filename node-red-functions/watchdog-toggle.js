function setNodeDisabled(nodes, targetId, disabled) {
    return nodes.map(n => n.id === targetId ? Object.assign({}, n, { d: disabled }) : n);
}

module.exports = { setNodeDisabled };
