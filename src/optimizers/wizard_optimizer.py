from .base_optimizer import BaseOptimizer
from src.evolvers import BaseEvolver, RecurrentEvolver
from src.evaluator import FailureDetectorEvaluator, BaseEvaluator
from src.generators import OpenAIGenerator, OpenRouterGenerator, BaseGenerator
from src.utils import parse_steps

import concurrent.futures
from typing import List, Optional
import asyncio
import random

METHOD_EVOL_PROMPT = """
Feedback: {feedback}
You are an Instruction Method Optimizer. Based on the feedback from the evolution failure case, optimize the method below to create a more effective instruction rewriting process without negatively impacting performance on other cases. Ensure that the complexity of the optimized method is not lower than the previous method.
If the feedback is "### PASSED", then come up with a better method than the current one to create a more complex and effective instruction rewriting process. Remember that the new method should not be very similar to the current method, be creative with new steps for the new method.

Current Method:
{current_method}

**Output Instructions**
Please generate the optimized method strictly using ONLY the given below format, do not add anything else:

```Optimized Method
Step 1:
#Methods List#
Describe how to generate a list of methods to make instructions more complex, incorporating the feedback

Step 2:
#Plan#
Explain how to create a comprehensive plan based on the Methods List

[Note]Add more steps here as you want to achieve the best method. The steps should align with the instruction domain/topic, and should not involve any tools or visualization, it should be text-only methods. The last step should always be #Finally Rewritten Instruction#.

Step N-1:
#Rewritten Instruction#
Do not generate new Instruction here, but please provide a detailed the process of executing the plan to rewrite the instruction. You are generating a guide to write a better instruction, NOT THE INSTRUCTION ITSELF.

Step N:
#Finally Rewritten Instruction#
Do not generate new Instruction here, but please provide the process to write the final rewritten instruction. You are generating a guide to write a better instruction, NOT THE INSTRUCTION ITSELF.
```
"""

class WizardOptimizer(BaseOptimizer):
    def __init__(self, generator: BaseGenerator, evaluator: BaseEvaluator) -> None:
        self.generator = generator
        self.evaluator = evaluator

    async def optimize(self, current_method: str, feedback: List[str], evolver: RecurrentEvolver, development_set: Optional[List] = None):
        async def generate_and_evaluate(feedback_item):
            optimized_prompt = METHOD_EVOL_PROMPT.format(feedback=feedback_item, current_method=current_method)
            evolved_method = await self.generator.agenerate(optimized_prompt, temperature=0.2)

            async def process_instruction(instruction):
                parsed_steps = parse_steps(evolved_method)
                new_method = evolver.build_new_method(parsed_steps, instruction)
                evolved_instruction = await self.generator.agenerate(prompt=new_method, temperature=0.2)
                try:
                    parsed_evolved_instruction = parse_steps(evolved_instruction)[-1]['step_instruction']
                    response = await self.generator.agenerate(prompt=parsed_evolved_instruction, temperature=0.2)
                    return parsed_evolved_instruction, response
                except:
                    response = await self.generator.agenerate(prompt=parsed_evolved_instruction, temperature=0.2)
                    return instruction, response

            results = await asyncio.gather(*[process_instruction(instruction) for instruction in development_set])
            evolved_instructions, responses = zip(*results)

            return evolved_method, list(evolved_instructions), list(responses)

        results = await asyncio.gather(*[generate_and_evaluate(item) for item in feedback])
        evolved_methods, all_evolved_instructions, all_responses = zip(*results)

        best_method, best_score = self.evaluator.select_best_method(
            evolved_methods, 
            [instr for method_instructions in all_evolved_instructions for instr in method_instructions],
            [resp for method_responses in all_responses for resp in method_responses]
        )

        return best_method, list(evolved_methods)