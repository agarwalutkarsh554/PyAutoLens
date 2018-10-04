import inspect
import itertools
import math
import os
import re
from functools import wraps

from scipy.special import erfinv

from autolens import conf
from autolens import exc
from autolens.conf import DefaultPriorConfig


class AttributeNameValue(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __iter__(self):
        return iter(self.tuple)

    @property
    def tuple(self):
        return self.name, self.value

    def __getitem__(self, item):
        return self.tuple[item]

    def __eq__(self, other):
        return self.tuple == other.tuple

    def __hash__(self):
        return hash(self.tuple)


class ConstantNameValue(AttributeNameValue):
    @property
    def constant(self):
        return self.value


class PriorNameValue(AttributeNameValue):
    @property
    def prior(self):
        return self.value


class PriorModelNameValue(AttributeNameValue):
    @property
    def prior_model(self):
        return self.value


def cast_collection(named_tuple):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return list(map(lambda tup: named_tuple(*tup), func(*args, **kwargs)))

        return wrapper

    return decorator


path = os.path.dirname(os.path.realpath(__file__))


class AbstractModel(object):
    def __add__(self, other):
        instance = self.__class__()

        def add_items(item_dict):
            for key, value in item_dict.items():
                if isinstance(value, list) and hasattr(instance, key):
                    setattr(instance, key, getattr(instance, key) + value)
                else:
                    setattr(instance, key, value)

        add_items(self.__dict__)
        add_items(other.__dict__)
        return instance


class ModelMapper(AbstractModel):
    """A mapper of priors formed by passing in classes to be reconstructed
        @DynamicAttrs
    """

    def __init__(self, config=None, width_config=None, **classes):
        """
        Parameters
        ----------
        config: DefaultPriorConfig
            An object that wraps a configuration

        Examples
        --------
        # The ModelMapper converts a set of classes whose input attributes may be modeled using a non-linear search,
        # to parameters with priors attached.

        # A config is passed into the model mapper to provide default setup values for the priors:

        mapper = ModelMapper(config)

        # All class instances that are to be generated by the model mapper are specified by adding classes to it:
        
        mapper = ModelMapper()

        mapper.sersic = light_profiles.EllipticalSersic
        mapper.gaussian = light_profiles.EllipticalGaussian)
        mapper.any_class = SomeClass

        # A PriorModel instance is created each time we add a class to the mapper. We can access those models using
        # the mapper attributes:

        sersic_model = mapper.sersic

        # This allows us to replace the default priors:

        mapper.sersic.intensity = GaussianPrior(mean=2., sigma=5.)

        # Or maybe we want to tie two priors together:

        mapper.sersic.phi = mapper.other_sersic.phi

        # This statement reduces the number of priors by one and means that the two sersic instances will always share
        # the same rotation angle phi.

        # We can then create instances of every class for a unit hypercube vector with length equal to
        # len(mapper.priors):

        model_instance = mapper.model_instance_for_vector([.4, .2, .3, .1])

        # The attributes of the model_instance are named the same as those of the mapper:

        sersic_1 = mapper.sersic_1

        # But this attribute is an instance of the actual EllipticalSersic:P class

        # A ModelMapper can be concisely constructed using keyword arguments:

        mapper = prior.ModelMapper(config, source_light_profile=light_profile.EllipticalSersic,
                                    lens_mass_profile=mass_profile.EllipticalCoredIsothermal,
                                    lens_light_profile=light_profile.EllipticalCoreSersic)
        """
        super(ModelMapper, self).__init__()

        self.config = (config or conf.instance.prior_default)
        self.width_config = (width_config or conf.instance.prior_width)

        for name, cls in classes.items():
            self.__setattr__(name, cls)

    def __setattr__(self, key, value):
        if isinstance(value, list) and len(value) > 0 and isinstance(value[0], AbstractPriorModel):
            value = ListPriorModel(value)
        elif inspect.isclass(value):
            value = PriorModel(value, config=self.config)
        super(ModelMapper, self).__setattr__(key, value)

    @property
    def prior_count(self):
        return len(self.prior_tuples_ordered_by_id)

    @property
    def constant_count(self):
        return len(self.constant_tuples_ordered_by_id)

    @property
    @cast_collection(PriorModelNameValue)
    def prior_model_tuples(self):
        """
        Returns
        -------
        prior_model_tuples: [(String, PriorModel)]
        """
        return list(filter(lambda t: isinstance(t[1], AbstractPriorModel), self.__dict__.items()))

    @property
    @cast_collection(PriorModelNameValue)
    def list_prior_model_tuples(self):
        """
        Returns
        -------
        list_prior_model_tuples: [(String, ListPriorModel)]
        """
        return list(filter(lambda t: isinstance(t[1], ListPriorModel), self.__dict__.items()))

    @property
    @cast_collection(PriorModelNameValue)
    def flat_prior_model_tuples(self):
        """
        Returns
        -------
        prior_model_tuples: [(String, PriorModel)]
            A list of tuples with the names of prior models and associated prior models. Names are fully qualified by
            all objects in which they are embedded.
        """
        return [("{}".format(prior_model_name), flat_prior_model) for
                prior_model_name, prior_model in
                self.prior_model_tuples for
                flat_prior_model_name, flat_prior_model in
                prior_model.flat_prior_model_tuples]

    @property
    @cast_collection(PriorNameValue)
    def prior_tuple_dict(self):
        """
        Returns
        -------
        prior_tuple_dict: {Prior: PriorTuple}
            The set of all priors associated with this mapper
        """
        return {prior_tuple.prior: prior_tuple
                for name, prior_model in self.prior_model_tuples
                for prior_tuple in prior_model.prior_tuples}.values()

    @property
    @cast_collection(ConstantNameValue)
    def constant_tuple_dict(self):
        """
        Returns
        -------
        constant_tuple_dict: {Constant: ConstantTuple}
            The set of all constants associated with this mapper
        """
        return {constant_tuple.constant: constant_tuple
                for name, prior_model in self.prior_model_tuples
                for constant_tuple in prior_model.constant_tuples}.values()

    @property
    @cast_collection(PriorNameValue)
    def prior_tuples_ordered_by_id(self):
        """
        Returns
        -------
        priors: [Prior]
            An ordered list of unique priors associated with this mapper
        """
        return sorted(list(self.prior_tuple_dict), key=lambda prior_tuple: prior_tuple.prior.id)

    @property
    @cast_collection(ConstantNameValue)
    def constant_tuples_ordered_by_id(self):
        """
        Returns
        -------
        constants: [(str, Constant)]
            A list of tuples mapping strings to constants constants ordered by id
        """
        return sorted(list(self.constant_tuple_dict), key=lambda constant_tuple: constant_tuple.constant.id)

    @property
    def prior_class_dict(self):
        """
        Returns
        -------
        prior_class_dict: {Prior: class}
            A dictionary mapping Priors to associated classes. Each prior will only have one class; if a prior is
            shared by two classes then only one of those classes will be in this dictionary.
        """
        return {prior: cls
                for prior_model_tuple in self.prior_model_tuples
                for prior, cls in
                prior_model_tuple.prior_model.prior_class_dict.items()}

    @property
    def prior_prior_model_dict(self):
        """
        Returns
        -------
        prior_prior_model_dict: {Prior: PriorModel}
            A dictionary mapping priors to associated prior models. Each prior will only have one prior model; if a
            prior is shared by two prior models then one of those prior models will be in this dictionary.
        """
        return {prior: prior_model[1] for prior_model in self.prior_model_tuples for _, prior in
                prior_model[1].prior_tuples}

    @property
    def prior_prior_model_name_dict(self):
        """
        Returns
        -------
        prior_prior_model_name_dict: {Prior: str}
            A dictionary mapping priors to the names of associated prior models. Each prior will only have one prior
            model name; if a prior is shared by two prior models then one of those prior model's names will be in this
            dictionary.
        """
        return {prior_tuple.prior: prior_model_tuple.name
                for prior_model_tuple in self.prior_model_tuples
                for prior_tuple in prior_model_tuple.prior_model.prior_tuples}

    @property
    def constant_prior_model_name_dict(self):
        """
        Returns
        -------
        prior_prior_model_name_dict: {Prior: str}
            A dictionary mapping priors to the names of associated prior models. Each prior will only have one prior
            model name; if a prior is shared by two prior models then one of those prior model's names will be in this
            dictionary.
        """
        return {constant_tuple.constant: prior_model_tuple.name
                for prior_model_tuple in self.prior_model_tuples
                for constant_tuple in prior_model_tuple.prior_model.constant_tuples}

    @property
    def prior_model_name_prior_tuples_dict(self):
        """
        Returns
        -------
        class_priors_dict: {String: [Prior]}
            A dictionary mapping_matrix the names of priors to lists of associated priors
        """
        return {name: list(prior_model.prior_tuples) for name, prior_model in self.prior_model_tuples}

    @property
    def prior_model_name_constant_tuples_dict(self):
        """
        Returns
        -------
        class_constants_dict: {String: [Constant]}
            A dictionary mapping_matrix the names of priors to lists of associated constants
        """
        return {name: list(prior_model.constant_tuples) for name, prior_model in self.prior_model_tuples}

    def physical_vector_from_hypercube_vector(self, hypercube_vector):
        """
        Parameters
        ----------
        hypercube_vector: [float]
            A unit hypercube vector

        Returns
        -------
        values: [float]
            A vector with values output by priors
        """
        return list(
            map(lambda prior_tuple, unit: prior_tuple.prior.value_for(unit), self.prior_tuples_ordered_by_id,
                hypercube_vector))

    def physical_values_ordered_by_class(self, hypercube_vector):
        """
        Parameters
        ----------
        hypercube_vector: [float]
            A unit vector

        Returns
        -------
        physical_values: [float]
            A list of physical values constructed by passing the values in the hypercube vector through associated
            priors.
        """
        model_instance = self.instance_from_unit_vector(hypercube_vector)
        result = []
        for instance_key in sorted(model_instance.__dict__.keys()):
            instance = model_instance.__dict__[instance_key]
            for attribute_key in sorted(instance.__dict__.keys()):

                value = instance.__dict__[attribute_key]

                if isinstance(value, tuple):
                    result.extend(list(value))
                else:
                    result.append(value)
        return result

    @property
    def physical_values_from_prior_medians(self):
        """
        Returns
        -------
        physical_values: [float]
            A list of physical values constructed by taking the mean possible value from each prior.
        """
        return self.physical_vector_from_hypercube_vector([0.5] * len(self.prior_tuple_dict))

    def instance_from_prior_medians(self):
        """
        Creates a list of physical values from the median values of the priors.

        Returns
        -------
        physical_values : [float]
            A list of physical values

        """
        return self.instance_from_unit_vector(unit_vector=[0.5] * len(self.prior_tuple_dict))

    def instance_from_unit_vector(self, unit_vector):
        """
        Creates a ModelInstance, which has an attribute and class instance corresponding to every PriorModel \
        attributed to this instance.

        This method takes as input a unit vector of parameter values, converting each to physical values via their \
        priors.

        Parameters
        ----------
        unit_vector: [float]
            A vector of physical parameter values.

        Returns
        -------
        model_instance : ModelInstance
            An object containing reconstructed model_mapper instances

        """
        arguments = dict(
            map(lambda prior_tuple, unit: (prior_tuple.prior, prior_tuple.prior.value_for(unit)),
                self.prior_tuples_ordered_by_id, unit_vector))

        return self.instance_for_arguments(arguments)

    def instance_from_physical_vector(self, physical_vector):
        """
        Creates a ModelInstance, which has an attribute and class instance corresponding to every PriorModel \
        attributed to this instance.

        This method takes as input a physical vector of parameter values, thus omitting the use of priors.

        Parameters
        ----------
        physical_vector: [float]
            A unit hypercube vector

        Returns
        -------
        model_instance : ModelInstance
            An object containing reconstructed model_mapper instances

        """
        arguments = dict(
            map(lambda prior_tuple, physical_unit: (prior_tuple.prior, physical_unit), self.prior_tuples_ordered_by_id,
                physical_vector))

        return self.instance_for_arguments(arguments)

    def instance_for_arguments(self, arguments):
        """
        Creates a ModelInstance, which has an attribute and class instance corresponding to every PriorModel
        attributed to this instance.

        Parameters
        ----------
        arguments : dict
            The dictionary representation of prior and parameter values. This is created in the model_instance_from_*
            routines.

        Returns
        -------
        model_instance : ModelInstance
            An object containing reconstructed model_mapper instances

        """

        model_instance = ModelInstance()

        for prior_model_tuple in self.prior_model_tuples:
            setattr(model_instance, prior_model_tuple.name,
                    prior_model_tuple.prior_model.instance_for_arguments(arguments))

        return model_instance

    def mapper_from_prior_arguments(self, arguments):
        """
        Creates a new model mapper from a dictionary mapping_matrix existing priors to new priors.

        Parameters
        ----------
        arguments: {Prior: Prior}
            A dictionary mapping_matrix priors to priors

        Returns
        -------
        model_mapper: ModelMapper
            A new model mapper with updated priors.
        """
        mapper = ModelMapper(config=self.config, width_config=self.width_config)

        for prior_model_tuple in self.prior_model_tuples:
            setattr(mapper, prior_model_tuple.name,
                    prior_model_tuple.prior_model.gaussian_prior_model_for_arguments(arguments))

        return mapper

    def mapper_from_gaussian_tuples(self, tuples):
        """
        Creates a new model mapper from a list of floats describing the mean values of gaussian priors. The widths \
        of the new priors are taken from the width_config. The new gaussian priors must be provided in the same \
        order as the priors associated with model.

        Parameters
        ----------
        tuples

        Returns
        -------
        mapper: ModelMapper
            A new model mapper with all priors replaced by gaussian priors.
        """
        tuples = [PriorNameValue(*tup) for tup in tuples]
        prior_tuples = self.prior_tuples_ordered_by_id
        prior_class_dict = self.prior_class_dict
        arguments = {}

        for i, prior_tuple in enumerate(prior_tuples):
            cls = prior_class_dict[prior_tuple.prior]
            width = self.width_config.get_for_nearest_ancestor(cls, prior_tuple.name)
            arguments[prior_tuple.prior] = GaussianPrior(tuples[i].name, max(tuples[i].prior, width))

        return self.mapper_from_prior_arguments(arguments)

    def mapper_from_gaussian_means(self, means):
        """
        Creates a new model mapper from a list of floats describing the mean values of gaussian priors. The widths of \
        the new priors are taken from the width_config. The new gaussian priors must be provided in the same order as \
        the priors associated with model.

        Parameters
        ----------
        means: [float]
            A list containing the means of the gaussian priors.

        Returns
        -------
        mapper: ModelMapper
            A new model mapper with all priors replaced by gaussian priors.
        """
        prior_tuples = self.prior_tuples_ordered_by_id
        prior_class_dict = self.prior_class_dict
        arguments = {}

        for i, prior_tuple in enumerate(prior_tuples):
            cls = prior_class_dict[prior_tuple.prior]
            width = self.width_config.get_for_nearest_ancestor(cls, prior_tuple.name)
            arguments[prior_tuple.prior] = GaussianPrior(means[i], width)

        return self.mapper_from_prior_arguments(arguments)

    @property
    def info(self):
        """
        Use the priors that make up the model_mapper to generate information on each parameter of the overall model.

        This information is extracted from each priors *model_info* property.
        """
        info = []

        for prior_model_name, prior_model in self.flat_prior_model_tuples:

            info.append(prior_model.cls.__name__ + '\n')

            prior_model_iterator = prior_model.prior_tuples + prior_model.constant_tuples

            for i, attribute_tuple in enumerate(prior_model_iterator):
                attribute = attribute_tuple[1]

                line = prior_model_name + '_' + attribute_tuple.name
                info.append(line + ' ' * (40 - len(line)) + attribute.info)

            info.append('')

        return '\n'.join(info)


class ModelInstance(AbstractModel):
    """
    An object to hold model instances produced by providing arguments to a model mapper.

    @DynamicAttrs
    """

    def instances_of(self, cls):
        return [instance for source in
                [list(self.__dict__.values())] + [ls for ls in self.__dict__.values() if isinstance(ls, list)] for
                instance in
                source if isinstance(instance, cls)]


class Attribute(object):
    _ids = itertools.count()

    def __init__(self):
        self.id = next(self._ids)


class Constant(Attribute):
    def __init__(self, value):
        """
        Represents a constant value. No prior is added to the model mapper for constants reducing the dimensionality
        of the nonlinear search.

        Parameters
        ----------
        value: Union(float, tuple)
            The value this constant should take.
        """
        self.value = value
        super().__init__()

    def __eq__(self, other):
        return self.value == other

    def __gt__(self, other):
        return self.value > other

    def __lt__(self, other):
        return self.value < other

    def __ne__(self, other):
        return self.value != other

    def __str__(self):
        return "Constant {}".format(self.value)

    def __hash__(self):
        return self.id

    @property
    def info(self):
        return 'Constant, value = {}'.format(self.value)


prior_number = 0


class Prior(Attribute):
    """An object used to mappers a unit value to an attribute value for a specific class attribute"""

    def value_for(self, unit):
        raise NotImplementedError()

    def __eq__(self, other):
        return self.id == other.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return "<Prior id={}>".format(self.id)


class UniformPrior(Prior):
    """A prior with a uniform distribution between a lower and upper limit"""

    def __init__(self, lower_limit=0., upper_limit=1.):
        """

        Parameters
        ----------
        lower_limit: Float
            The lowest value this prior can return
        upper_limit: Float
            The highest value this prior can return
        """
        if lower_limit == upper_limit:
            raise exc.PriorException("Uniform priors cannot have equal lower and upper limits")
        self.upper_limit = upper_limit
        super(UniformPrior, self).__init__()
        self.lower_limit = lower_limit

    def value_for(self, unit):
        """

        Parameters
        ----------
        unit: Float
            A unit hypercube value between 0 and 1
        Returns
        -------
        value: Float
            A value for the attribute between the upper and lower limits
        """
        return self.lower_limit + unit * (self.upper_limit - self.lower_limit)

    @property
    def mean(self):
        return (self.upper_limit - self.lower_limit) / 2

    @mean.setter
    def mean(self, new_value):
        difference = new_value - self.mean
        self.lower_limit += difference
        self.upper_limit += difference

    @property
    def info(self):
        """The line of text describing this prior for the model_mapper.info file"""
        return 'UniformPrior, lower_limit = ' + str(self.lower_limit) + ', upper_limit = ' + str(self.upper_limit)


class GaussianPrior(Prior):
    """A prior with a gaussian distribution"""

    def __init__(self, mean, sigma):
        super(GaussianPrior, self).__init__()
        self.mean = mean
        self.sigma = sigma

    def value_for(self, unit):
        """

        Parameters
        ----------
        unit: Float
            A unit hypercube value between 0 and 1
        Returns
        -------
        value: Float
            A value for the attribute biased to the gaussian distribution
        """
        return self.mean + (self.sigma * math.sqrt(2) * erfinv((unit * 2.0) - 1.0))

    @property
    def info(self):
        """The line of text describing this prior for the model_mapper.info file"""
        return 'GaussianPrior, mean = ' + str(self.mean) + ', sigma = ' + str(self.sigma)


class TuplePrior(object):
    """
    A prior comprising one or more priors in a tuple
    """

    def __setattr__(self, key, value):
        try:
            if isinstance(value, float) or isinstance(value, int):
                super().__setattr__(key, Constant(value))
                return
        except IndexError:
            pass
        super(TuplePrior, self).__setattr__(key, value)

    @property
    @cast_collection(PriorNameValue)
    def prior_tuples(self):
        """
        Returns
        -------
        priors: [(String, Prior)]
            A list of priors contained in this tuple
        """
        return list(filter(lambda t: isinstance(t[1], Prior), self.__dict__.items()))

    @property
    @cast_collection(ConstantNameValue)
    def constant_tuples(self):
        """
        Returns
        -------
        constants: [(String, Constant)]
            A list of constants
        """
        return list(sorted(filter(lambda t: isinstance(t[1], Constant), self.__dict__.items()), key=lambda tup: tup[0]))

    def value_for_arguments(self, arguments):
        """
        Parameters
        ----------
        arguments: {Prior: float}
            A dictionary of arguments

        Returns
        -------
        tuple: (float,...)
            A tuple of float values
        """

        def convert(tup):
            if hasattr(tup, "prior"):
                return arguments[tup.prior]
            return tup.constant.value

        return tuple(map(convert, sorted(self.prior_tuples + self.constant_tuples, key=lambda tup: tup.name)))

    def gaussian_tuple_prior_for_arguments(self, arguments):
        """
        Parameters
        ----------
        arguments: {Prior: float}
            A dictionary of arguments

        Returns
        -------
        tuple_prior: TuplePrior
            A new tuple prior with gaussian priors
        """
        tuple_prior = TuplePrior()
        for prior_tuple in self.prior_tuples:
            setattr(tuple_prior, prior_tuple.name, arguments[prior_tuple.prior])
        return tuple_prior


class AbstractPriorModel:
    """
    Abstract model that maps a set of priors to a particular class. Must be overridden by any prior model so that the \
    model mapper recognises its prior model attributes.
    """
    _ids = itertools.count()

    @property
    def flat_prior_model_tuples(self):
        """
        Returns
        -------
        prior_models: [(str, AbstractPriorModel)]
            A list of prior models associated with this instance
        """
        raise NotImplementedError("PriorModels must implement the flat_prior_models property")

    @property
    def prior_tuples(self):
        raise NotImplementedError()

    @property
    def constant_tuples(self):
        raise NotImplementedError()

    @property
    def prior_class_dict(self):
        raise NotImplementedError()

    def instance_for_arguments(self, arguments):
        raise NotImplementedError()


class PriorModel(AbstractPriorModel):
    """Object comprising class and associated priors
        @DynamicAttrs
    """

    @property
    def flat_prior_model_tuples(self):
        return [("", self)]

    def __init__(self, cls, config=None):
        """
        Parameters
        ----------
        cls: class
            The class associated with this instance
        """

        self.cls = cls
        self.config = (config or conf.instance.prior_default)
        self.width_config = conf.instance.prior_width

        self.component_number = next(self._ids)

        arg_spec = inspect.getfullargspec(cls.__init__)

        try:
            defaults = dict(zip(arg_spec.args[-len(arg_spec.defaults):], arg_spec.defaults))
        except TypeError:
            defaults = {}

        args = arg_spec.args[1:]

        if 'settings' in defaults:
            del defaults['settings']
        if 'settings' in args:
            args.remove('settings')

        for arg in args:
            if arg in defaults and isinstance(defaults[arg], tuple):
                tuple_prior = TuplePrior()
                for i in range(len(defaults[arg])):
                    attribute_name = "{}_{}".format(arg, i)
                    setattr(tuple_prior, attribute_name, self.make_prior(attribute_name, cls))
                setattr(self, arg, tuple_prior)
            else:
                setattr(self, arg, self.make_prior(arg, cls))

    def make_prior(self, attribute_name, cls):
        """
        Create a prior for an attribute of a class with a given name. The prior is created by searching the default
        prior config for the attribute.

        Entries in configuration with a u become uniform priors; with a g become gaussian priors; with a c become
        constants.

        If prior configuration for a given attribute is not specified in the configuration for a class then the
        configuration corresponding to the parents of that class is searched. If no configuration can be found then a
        prior exception is raised.

        Parameters
        ----------
        attribute_name: str
            The name of the attribute for which a prior is created
        cls: class
            The class to which the attribute belongs

        Returns
        -------
        prior: Prior
            A prior

        Raises
        ------
        exc.PriorException
            If no configuration can be found
        """
        config_arr = self.config.get_for_nearest_ancestor(cls, attribute_name)
        if config_arr[0] == "u":
            return UniformPrior(config_arr[1], config_arr[2])
        elif config_arr[0] == "g":
            return GaussianPrior(config_arr[1], config_arr[2])
        elif config_arr[0] == "c":
            return Constant(config_arr[1])
        raise exc.PriorException(
            "Default prior for {} has no type indicator (u - Uniform, g - Gaussian, c - Constant".format(
                attribute_name))

    def linked_model_for_class(self, cls, make_constants_variable=False, **kwargs):
        """
        Create a PriorModel wrapping the specified class with attributes from this instance. Priors can be overridden
        using keyword arguments. Any constructor arguments of the new class for which there is no attribute associated
        with this class and no keyword argument are created from config.

        If make_constants_variable is True then constants associated with this instance will be used to set the mean
        of priors in the new instance rather than overriding them.

        Parameters
        ----------
        cls: class
            The class that the new PriorModel will wrap
        make_constants_variable: bool
            If True constants from this instance will be used to determine the mean values for priors in the new
            instance rather than overriding them
        kwargs
            Keyword arguments passed in here are used to override attributes from this instance or add new attributes

        Returns
        -------
        new_model: PriorModel
            A new prior model with priors derived from this instance
        """
        constructor_args = inspect.getfullargspec(cls).args
        attribute_tuples = self.attribute_tuples
        new_model = PriorModel(cls, self.config)
        for attribute_tuple in attribute_tuples:
            name = attribute_tuple.name
            if name in constructor_args or (
                    is_tuple_like_attribute_name(name) and tuple_name(name) in constructor_args):
                attribute = kwargs[name] if name in kwargs else attribute_tuple.value
                if make_constants_variable and isinstance(attribute, Constant):
                    new_attribute = getattr(new_model, name)
                    if isinstance(new_attribute, Prior):
                        new_attribute.mean = attribute.value
                        continue
                setattr(new_model, name, attribute)
        return new_model

    def __setattr__(self, key, value):
        if key != "component_number":
            try:
                if "_" in key:
                    tuple_name = key.split("_")[0]
                    tuple_prior = [v for k, v in self.tuple_prior_tuples if tuple_name == k][0]
                    setattr(tuple_prior, key, value)
                    return
            except IndexError:
                pass
            if isinstance(value, float) or isinstance(value, int):
                super().__setattr__(key, Constant(value))
                return
        super(PriorModel, self).__setattr__(key, value)

    def __getattr__(self, item):
        try:
            if "_" in item:
                return getattr([v for k, v in self.tuple_prior_tuples if item.split("_")[0] == k][0], item)

        except IndexError:
            pass
        self.__getattribute__(item)

    @property
    @cast_collection(PriorNameValue)
    def tuple_prior_tuples(self):
        """
        Returns
        -------
        tuple_prior_tuples: [(String, TuplePrior)]
        """
        return list(filter(lambda t: type(t[1]) is TuplePrior, self.__dict__.items()))

    @property
    @cast_collection(PriorNameValue)
    def direct_prior_tuples(self):
        """
        Returns
        -------
        direct_priors: [(String, Prior)]
        """
        return list(filter(lambda t: isinstance(t[1], Prior), self.__dict__.items()))

    @property
    @cast_collection(PriorNameValue)
    def prior_tuples(self):
        """
        Returns
        -------
        priors: [(String, Prior))]
        """
        return [prior for tuple_prior in self.tuple_prior_tuples for prior in
                tuple_prior[1].prior_tuples] + self.direct_prior_tuples

    @property
    @cast_collection(ConstantNameValue)
    def direct_constant_tuples(self):
        """
        Returns
        -------
        constants: [(String, Constant)]
            A list of constants
        """
        return list(filter(lambda t: isinstance(t[1], Constant), self.__dict__.items()))

    @property
    @cast_collection(ConstantNameValue)
    def constant_tuples(self):
        """
        Returns
        -------
        constants: [(String, Constant)]
        """
        return [constant_tuple for tuple_prior in self.tuple_prior_tuples for constant_tuple in
                tuple_prior[1].constant_tuples] + self.direct_constant_tuples

    @property
    @cast_collection(AttributeNameValue)
    def attribute_tuples(self):
        return self.prior_tuples + self.constant_tuples

    @property
    def prior_class_dict(self):
        return {prior[1]: self.cls for prior in self.prior_tuples}

    def instance_for_arguments(self, arguments: {Prior: float}):
        """
        Create an instance of the associated class for a set of arguments

        Parameters
        ----------
        arguments: {Prior: float}
            Dictionary mapping_matrix priors to attribute analysis_path and value pairs

        Returns
        -------
            An instance of the class
        """
        model_arguments = {t.name: arguments[t.prior] for t in self.direct_prior_tuples}
        constant_arguments = {t.name: t.constant.value for t in self.direct_constant_tuples}
        for tuple_prior in self.tuple_prior_tuples:
            model_arguments[tuple_prior.name] = tuple_prior.prior.value_for_arguments(arguments)

        return self.cls(**{**model_arguments, **constant_arguments})

    def gaussian_prior_model_for_arguments(self, arguments):
        """
        Create a new instance of model mapper with a set of Gaussian priors based on tuples provided by a previous \
        nonlinear search.

        Parameters
        ----------
        arguments: [(float, float)]
            Tuples providing the mean and sigma of gaussians

        Returns
        -------
        new_model: ModelMapper
            A new model mapper populated with Gaussian priors
        """
        new_model = PriorModel(self.cls, self.config)

        model_arguments = {t.name: arguments[t.prior] for t in self.direct_prior_tuples}

        for tuple_prior_tuple in self.tuple_prior_tuples:
            setattr(new_model, tuple_prior_tuple.name,
                    tuple_prior_tuple.prior.gaussian_tuple_prior_for_arguments(arguments))
        for prior_tuple in self.direct_prior_tuples:
            setattr(new_model, prior_tuple.name, model_arguments[prior_tuple.name])
        for constant_tuple in self.constant_tuples:
            setattr(new_model, constant_tuple.name, constant_tuple.constant)

        return new_model


class ListPriorModel(list, AbstractPriorModel):
    @property
    def flat_prior_model_tuples(self):
        return [flat_prior_model for prior_model in self for flat_prior_model in prior_model.flat_prior_model_tuples]

    def __init__(self, prior_models):
        """
        A prior model used to represent a list of prior models for convenience.

        Parameters
        ----------
        prior_models: [PriorModel]
            A list of prior models
        """
        self.component_number = next(self._ids)
        super().__init__(prior_models)

    def instance_for_arguments(self, arguments):
        """
        Parameters
        ----------
        arguments: {Prior: float}
            A dictionary of arguments

        Returns
        -------
        model_instances: [object]
            A list of instances constructed from the list of prior models.
        """
        return [prior_model.instance_for_arguments(arguments) for prior_model in self]

    def gaussian_prior_model_for_arguments(self, arguments):
        """
        Parameters
        ----------
        arguments: {Prior: float}
            A dictionary of arguments

        Returns
        -------
        prior_models: [PriorModel]
            A new list of prior models with gaussian priors
        """
        return ListPriorModel(
            [prior_model.gaussian_prior_model_for_arguments(arguments) for prior_model in self])

    @property
    @cast_collection(PriorNameValue)
    def prior_tuples(self):
        """
        Returns
        -------
        priors: [(String, Union(Prior, TuplePrior))]
        """
        return set([prior for prior_model in self for prior in prior_model.prior_tuples])

    @property
    @cast_collection(ConstantNameValue)
    def constant_tuples(self):
        """
        Returns
        -------
        priors: [(String, Union(Prior, TuplePrior))]
        """
        return set([constant for prior_model in self for constant in prior_model.constant_tuples])

    @property
    def prior_class_dict(self):
        return {prior: cls for prior_model in self for prior, cls in prior_model.prior_class_dict.items()}


def is_tuple_like_attribute_name(attribute_name):
    """
    Determine if a string matches the pattern "{attribute_name}_#", that is if it seems to be a tuple.

    Parameters
    ----------
    attribute_name: str
        The name of some attribute that may refer to a tuple.

    Returns
    -------
    is_tuple_like: bool
        True iff the attribute name looks like that which refers to a tuple.
    """
    pattern = re.compile("^[a-zA-Z_0-9]*_[0-9]$")
    return pattern.match(attribute_name)


def tuple_name(attribute_name):
    """
    Extract the name of a tuple attribute from the name of one of its components, e.g. centre_0 -> centre

    Parameters
    ----------
    attribute_name: str
        The name of an attribute which is a component of a tuple

    Returns
    -------
    tuple_name: str
        The name of the tuple of which the attribute is a member
    """
    return "_".join(attribute_name.split("_")[:-1])
