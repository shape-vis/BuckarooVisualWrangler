class CacheController {
    constructor(data) {
        this.detectors = null;
        this.model = new CacheModel(data);
        this.detectors = null;
    }

    /**
     * Init of cache controller, the controller which interfaces between the browser MVC
     * @returns {Promise<void>}
     */
    async init(detectors) {
        this.detectors = detectors;
        await this.model.runDetectors(detectors);
        this.model.createEmptyDataTable(data);
        this.model.selectRandomNonErrorSubset(populationSize);
    }

}