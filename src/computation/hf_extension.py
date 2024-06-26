from dataclasses import dataclass
from typing import Dict, List, Union, Any
import torch
from torch import nn
from types import MethodType
from transformers import Pipeline
from transformers.utils.generic import ModelOutput
from .fisher import hess
from ..arithmetics.weights_wrapper import ArchitectureTensor

class HessianCallback:
    def __init__(self, model):
        self.model = model
        self.arch = ArchitectureTensor(model)
        self.hessian = self.arch.zeros()
        self.num_samples = 0

    def __call__(self, outputs: ModelOutput):
        H = hess(self.model, outputs.logits)
        self.add_sample(H)
        
        # detach as hf needs clean logits with no gradient
        outputs.logits = outputs.logits.detach()
        
    def add_sample(self, sample_hessian: List[torch.Tensor]):
        self.num_samples += 1
        self.hessian += self.arch.to_tensor(sample_hessian)
    
    @torch.no_grad()
    def get_hessian(self) -> torch.Tensor:
        return self.hessian / self.num_samples
    
    
def add_callback(func, callback):
    '''This functions injects a callback into a method of a class.
    
    Args:
        func (function): the method to inject the callback into
        callback (function): the callback to inject
    Returns:    
        function: the new method with the callback injected
    '''
    def new_func(self, *args, **kwargs):
        outputs = func.__func__(self, *args, **kwargs)
        callback(outputs)
        return outputs
    return new_func


def fisher_matrix(pipe: Pipeline, dataset: Any) -> torch.Tensor:
    """Computes the Fisher Information Matrix diagonal approximation for the given dataset and model pipeline.
        Args:
            pipe (Pipeline): the pipeline model
            dataset (Any): the dataset to compute the Fisher Information Matrix for
        Returns:
            List[torch.Tensor]: the Fisher Information Matrix diagonal approximation
    """
    model = pipe.model
    hess_callback = HessianCallback(model)

    # Modify the pipeline to compute the hessian
    pipe.get_inference_context = lambda *_: torch.enable_grad   # enable gradient computation
    pipe._forward = MethodType(add_callback(pipe._forward, hess_callback), pipe) # add the callback to the forward method

    predicted = list(pipe(dataset, batch_size=1))

    hessian = hess_callback.get_hessian()
    return hessian