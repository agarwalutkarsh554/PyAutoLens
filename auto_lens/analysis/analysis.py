from auto_lens.analysis import non_linear
from auto_lens.analysis import model_mapper as mm
from auto_lens.analysis import fitting
from auto_lens.imaging import grids
from auto_lens.analysis import ray_tracing
from auto_lens import exc
import logging

# TODO: Pipelines that modify images, pipeline with or without hyper_image, pipeline with prior modification

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.level = logging.DEBUG

attribute_map = {"pixelization_class": "pixelization",
                 "instrumentation_class": "instrumentation",
                 "lens_galaxy_priors": "lens_galaxies",
                 "source_galaxy_priors": "source_galaxies"}


class Analysis(object):
    def __init__(self, model_mapper=mm.ModelMapper(), non_linear_optimizer=None,
                 fitting_function=fitting.likelihood_for_image_tracer_pixelization_and_instrumentation, **kwargs):
        """
        A generic analysis class. Model classes are provided in the constructor as keyword arguments. These classes act
        as variables. Each fitting in the analysis will use a new set of model instances generated by these classes.

        Any model instance required in the analysis that does not have a model class passed in the constructor must
        be passed into the run argument.

        Parameters
        ----------
        model_mapper: ModelMapper
            A class used to bridge between non linear unit vectors and class instances
        non_linear_optimizer: NonLinearOptimizer
            A wrapper around a library that searches an n-dimensional space by providing unit vector hypercubes to
            the analysis.
        kwargs
            The model classes that produce variable model instances to be used in each fitting

        Examples
        --------
        # We create an analysis which will be used to try out different attributes for a lens galaxy
        analysis = Analysis(lens_galaxy_priors=[galaxy_prior])

        # Now when we run the analysis we have to pass in source galaxies, pixelization and instrumentation. These will
        # remain constant throughout the analysis.
        result = analysis.run(image=image, source_galaxies=[source_galaxy], mask=mask,
                              pixelization=pixelization, instrumentation=instrumentation)
        """
        self.model_mapper = model_mapper
        self.non_linear_optimizer = non_linear_optimizer if non_linear_optimizer is not None else non_linear.MultiNest(
            model_mapper)
        self.fitting_function = fitting_function
        self.included_attributes = []

        for key, value in kwargs.items():
            setattr(self, key, value)
            self.included_attributes.append(key)

        self.missing_attributes = [value for key, value in attribute_map.items() if key not in self.included_attributes]

        def add_galaxy_priors(name):
            if hasattr(self, name):
                for galaxy_prior in getattr(self, name):
                    galaxy_prior.attach_to_model_mapper(model_mapper)

        add_galaxy_priors('lens_galaxy_priors')
        add_galaxy_priors('source_galaxy_priors')

        def add_class(name):
            attribute_name = "{}_class".format(name)
            if hasattr(self, attribute_name):
                model_mapper.add_class(name, getattr(self, attribute_name))

        add_class('instrumentation')
        add_class('pixelization')

    def run(self, image, mask, **kwargs):
        """
        Runs the analysis. Any model classes corresponding to model instances required in the analysis that were not
        passed into the constructor must be passed in here as keyword arguments.

        Parameters
        ----------
        image: Image
            An image to fit for
        mask: Mask
            A mask describing the region of the image we are going to analyse
        kwargs
            The model instances that are to remain constant throughout this analysis

        Returns
        -------
        result: Result
            An object comprising the final model instances generated and a corresponding likelihood
        """
        for attribute in self.missing_attributes:
            if attribute not in kwargs:
                raise exc.PipelineException("{} is required".format(attribute))

        for key in kwargs.keys():
            if key not in self.missing_attributes:
                raise exc.PipelineException("A model has been defined for {}".format(key))

        image_grid_collection = grids.GridCoordsCollection.from_mask(mask)
        run = Analysis.Run(image, image_grid_collection, self.model_mapper, self.fitting_function)

        kwargs.update(self.__dict__)

        for key, value in kwargs.items():
            setattr(run, key, value)

        self.non_linear_optimizer.run(run.fitness_function, self.model_mapper.priors_ordered_by_id)

        return self.__class__.Result(run)

    class Result(object):
        def __init__(self, run):
            """
            An object comprising the final model instances generated and a corresponding likelihood

            Parameters
            ----------
            run: Run
                A run object created when the analysis is run
            """
            for name in attribute_map.values():
                setattr(self, name, getattr(run, name))

            self.likelihood = run.likelihood

    class Run(object):
        def __init__(self, image, image_grid_collection, model_mapper, fitting_function):
            """
            An object created when the analysis is run. Model class and model instance arguments are set by the analysis

            Parameters
            ----------
            image: Image
                An image to be analysed
            image_grid_collection: GridCoordinateCollection
                An object storing grids used to map between the image and arrays used in the analysis
            model_mapper: ModelMapper
                A class used to bridge between non linear unit vectors and class instances
            """
            self.image = image
            self.image_grid_collection = image_grid_collection
            self.model_mapper = model_mapper
            self.fitting_function = fitting_function

        # noinspection PyAttributeOutsideInit
        def fitness_function(self, physical_values):
            """
            A function that constructs model instances and determines a likelihood

            Parameters
            ----------
            physical_values: [float]
                A vector of physical values from a non-linear search

            Returns
            -------
            likelihood: float
                The likelihood that this model instance fits the image
            """

            model_instance = self.model_mapper.from_physical_vector(physical_values)

            if hasattr(self, "pixelization_class"):
                self.pixelization = model_instance.pixelization
            if hasattr(self, "instrumentation_class"):
                self.instrumentation = model_instance.instrumentation
            if hasattr(self, "lens_galaxy_priors"):
                self.lens_galaxies = list(
                    map(lambda galaxy_prior: galaxy_prior.galaxy_for_model_instance(model_instance),
                        self.lens_galaxy_priors))
            if hasattr(self, "source_galaxy_priors"):
                self.source_galaxies = list(
                    map(lambda galaxy_prior: galaxy_prior.galaxy_for_model_instance(model_instance),
                        self.source_galaxy_priors))

            # Construct a ray tracer
            tracer = ray_tracing.Tracer(self.lens_galaxies, self.source_galaxies, self.image_grid_collection)
            # Determine likelihood:
            self.likelihood = self.fitting_function(self.image,
                                                    tracer,
                                                    self.pixelization,
                                                    self.instrumentation)
            return self.likelihood


class ModelAnalysis(Analysis):
    def __init__(self, lens_galaxy_priors, source_galaxy_priors, model_mapper=mm.ModelMapper(),
                 non_linear_optimizer=None):
        """
        A class encapsulating an analysis. An analysis takes an image and a set of galaxy priors describing an
        assumed model and applies a pixelization and non linear optimizer to find the best possible fit between the
        image and model.

        Parameters
        ----------
        lens_galaxy_priors: [GalaxyPrior]
            A list of prior instances describing the lens
        source_galaxy_priors: [GalaxyPrior]
            A list of prior instances describing the source
        model_mapper: ModelMapper
            A class used to bridge between non linear unit vectors and class instances
        non_linear_optimizer: NonLinearOptimizer
            A wrapper around a library that searches an n-dimensional space by providing unit vector hypercubes to
            the analysis.
        """

        super().__init__(model_mapper=model_mapper, non_linear_optimizer=non_linear_optimizer,
                         lens_galaxy_priors=lens_galaxy_priors, source_galaxy_priors=source_galaxy_priors)


class HyperparameterAnalysis(Analysis):
    def __init__(self, pixelization_class, instrumentation_class, model_mapper=mm.ModelMapper(),
                 non_linear_optimizer=None):
        """
        An analysis to improve hyperparameter settings. This optimizes pixelization and instrumentation.

        Parameters
        ----------
        pixelization_class: Pixelization
            A class describing how the source plane should be pixelized
        instrumentation_class: Instrumentation
            A class describing instrumental effects
        model_mapper: ModelMapper
            A class used to bridge between non linear unit vectors and class instances
        non_linear_optimizer: NonLinearOptimizer
            A wrapper around a library that searches an n-dimensional space by providing unit vector hypercubes to
            the analysis.
        """
        super().__init__(model_mapper, non_linear_optimizer, pixelization_class=pixelization_class,
                         instrumentation_class=instrumentation_class)

# class Pipeline(object):
#     def __init__(self, *analyses):
#         """
#         Generic pipeline. Runs a series of analyses, passing the results of one analysis into the following analysis
#         where required.
#
#         Parameters
#         ----------
#         analyses: [Analysis]
#             A series of analyses
#         """
#         self.analyses = analyses
#
#     def run(self, image, mask, **arg_dict):
#         """
#         Run the pipeline. Each analysis will be run in turn with the results of one analysis being passed into the next.
#         Any missing model classes in the first analysis must have a corresponding model instance passed in as a keyword
#         argument to the run function.
#
#         Parameters
#         ----------
#         image: Image
#             An image to fit for
#         mask: Mask
#             A mask describing the region of the image we are going to analyse
#         arg_dict
#             The model instances that are to remain constant for the first analysis
#
#         Returns
#         -------
#         results: [Result]
#             A list of objects describing the results for each analysis
#         """
#
#         # Define a list to keep results in
#         results = []
#         # Iterate through the analyses
#         for analysis in self.analyses:
#             # Take required arguments for an analysis from the arg dict
#             args = {key: value for key, value in arg_dict.items() if key in analysis.missing_attributes}
#             # Run the analysis
#             result = analysis.run(image, mask, **args)
#             # Add the results of the analysis to the list of results
#             results.append(result)
#             # Use the previous result to overwrite the arg dict
#             arg_dict = result.__dict__
#
#         return results
#
#
# class MainPipeline(Pipeline):
#     def __init__(self, *model_analyses, hyperparameter_analysis):
#         """
#         The primary pipeline. This pipeline runs a series of model analyses with hyperparameter analyses in between.
#
#         Parameters
#         ----------
#         model_analyses: [ModelAnalysis]
#             A series of analysis, each with a fixed model, pixelization and instrumentation but variable model instance.
#         hyperparameter_analysis: HyperparameterAnalysis
#             An analysis with a fixed model instance but variable pixelization and instrumentation instances.
#
#         Examples
#         --------
#
#         # We define a pipeline that is a series of analyses
#         pipeline = pl.Pipeline(
#
#             # The first analysis is built to vary all galaxy priors and hyperparameters simultaneously
#             pl.Analysis(model_mapper=mm.ModelMapper(config=test_config)
#                         pixelization_class=MockPixelization,
#                         instrumentation_class=MockInstrumentation,
#                         lens_galaxy_priors=[galaxy_prior.GalaxyPrior()],
#                         source_galaxy_priors=[galaxy_prior.GalaxyPrior()]),
#
#             # The second analysis focuses on hyperparameters
#             pl.Analysis(model_mapper=mm.ModelMapper(config=test_config)
#                         pixelization_class=MockPixelization,
#                         instrumentation_class=MockInstrumentation),
#
#             # The third analysis focuses on galaxy models
#             pl.Analysis(model_mapper=mm.ModelMapper(config=test_config)
#                         lens_galaxy_priors=[galaxy_prior.GalaxyPrior()],
#                         source_galaxy_priors=[galaxy_prior.GalaxyPrior()]),
#
#             # The final analysis focuses on the source galaxy
#             pl.Analysis(model_mapper=mm.ModelMapper(config=test_config)
#                         source_galaxy_priors=[galaxy_prior.GalaxyPrior()])
#         )
#
#         # We run the pipeline and obtain a list of results, one for each analysis
#         results = pipeline.run(MockImage(), MockMask())
#         """
#         analyses = []
#         for model_analysis in model_analyses:
#             analyses.append(model_analysis)
#             analyses.append(hyperparameter_analysis)
#         super().__init__(*analyses)
#
#     def run(self, image, mask, pixelization=None, instrumentation=None):
#         """
#         Run this pipeline on an image and mask with a given initial pixelization and instrumentation.
#
#         Parameters
#         ----------
#         image: Image
#             The image to be fit
#         mask: Mask
#             A mask describing which parts of the image are to be included
#         pixelization: Pixelization
#             The initial pixelization of the source plane
#         instrumentation: Instrumentation
#             The initial instrumentation
#
#         Returns
#         -------
#         results_tuple: ([ModelAnalysis.Result], [HyperparameterAnalysis.Result])
#             A tuple with a list of results from each model analysis and a list of results from each hyperparameter
#             analysis
#         """
#
#         results = super(MainPipeline, self).run(image, mask, pixelization=pixelization, instrumentation=instrumentation)
#
#         return [result for i, result in enumerate(results) if i % 2 == 0], [result for i, result in enumerate(results)
#                                                                             if i % 2 != 0]
